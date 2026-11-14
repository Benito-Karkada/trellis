#!/usr/bin/env python3
"""Collect Ferb source for a Trellis missing-grader CSV/JSON report.

Prefer verified local coding archives; --refresh downloads fresh private ZIPs.
Never imports or executes the downloaded grading source.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from zipfile import BadZipFile, ZipFile

import requests
from download_vocareum_coding_exercises import VocareumClient

ROOT = Path(__file__).resolve().parents[1]
MAX_FERB_BYTES = 4 * 1024 * 1024


def read_rows(path):
    if path.suffix.casefold() == '.json':
        rows = json.loads(path.read_text())
    else:
        with path.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('The report must contain a list of rows.')
    return rows


def cached_parts(root, course):
    result = {}
    for path in sorted(root.glob('exercises/*/*/manifest.json')):
        data = json.loads(path.read_text())
        if str(data.get('course_id')) != str(course):
            continue
        part = str(data.get('part_id', ''))
        if part in result:
            raise ValueError(f'Duplicate cached Vocareum part {part}; review the archive manifests.')
        result[part] = (data, path.parent)
    return result


def unique_source(candidates):
    if not candidates:
        raise FileNotFoundError('No Ferb.py found in the private folder.')
    unique = {hashlib.sha256(content).hexdigest() for name, content in candidates}
    if len(unique) != 1:
        raise ValueError('Multiple different Ferb.py files found; review the archive.')
    return candidates[0]


def cached_ferb(folder):
    private = folder / 'private'
    candidates = []
    for path in sorted(private.rglob('*')):
        if path.is_symlink() or not path.is_file() or path.name.casefold() != 'ferb.py':
            continue
        if not path.resolve().is_relative_to(private.resolve()):
            raise ValueError('A cached file escapes the private folder.')
        if path.stat().st_size > MAX_FERB_BYTES:
            raise ValueError('Ferb.py exceeds the 4 MB limit.')
        candidates.append((str(path.relative_to(folder)), path.read_bytes()))
    return unique_source(candidates)


def zip_ferb(path):
    candidates = []
    with ZipFile(path) as archive:
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            if name.name.casefold() != 'ferb.py' or entry.is_dir():
                continue
            if name.is_absolute() or '..' in name.parts or '\\' in entry.filename:
                raise ValueError('Unsafe Ferb.py path in ZIP.')
            if entry.file_size > MAX_FERB_BYTES:
                raise ValueError('Ferb.py exceeds the 4 MB limit.')
            with archive.open(entry) as stream:
                content = stream.read(MAX_FERB_BYTES + 1)
            if len(content) > MAX_FERB_BYTES:
                raise ValueError('Ferb.py exceeds the 4 MB limit.')
            candidates.append((entry.filename, content))
    return unique_source(candidates)


def remote_parts(client, course):
    result = {}
    # These helpers paginate ALL assignments and their parts. Embedded parts
    # on the first assignments page are not a complete course inventory.
    for assignment in client.assignments(course):
        aid = str(assignment['id'])
        for part in client.parts(course, aid):
            pid = str(part['id'])
            if pid in result and result[pid]['assignment_id'] != aid:
                raise ValueError(f'Ambiguous assignment for Vocareum part {pid}.')
            result[pid] = {'assignment_id': aid, 'assignment_name': assignment.get('name', ''),
                           'part_id': pid, 'part_name': part.get('name', ''), 'course_id': str(course)}
    return result


def download_ferb(client, course, assignment, part):
    transaction = client.start_export(str(course), str(assignment), str(part), 'private')
    url = client.await_export(transaction)
    with tempfile.TemporaryDirectory(prefix='trellis-ferb-') as directory:
        target = Path(directory) / 'private.zip'
        client.download(url, target)  # No API Authorization header on signed downloads.
        return zip_ferb(target)


def save_source(out, row, source, source_path, course, assignment, origin):
    trellis_id = str(row.get('part_id', ''))
    if not trellis_id.isdigit():
        raise ValueError('The report has an invalid Trellis part ID.')
    title = str(row.get('title', '')).strip()
    slug = re.sub(r'[^a-zA-Z0-9._-]+', '-', title).strip('-')[:100] or 'exercise'
    folder = out / f'part-{trellis_id}--{slug}'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / 'Ferb.py'
    if target.exists() and target.read_bytes() != source:
        raise ValueError('Existing Ferb.py differs; move it aside before replacing it.')
    target.touch(mode=0o600)
    target.write_bytes(source)
    target.chmod(0o600)
    metadata = {'trellis_part_id': int(trellis_id), 'trellis_assignment_id': row.get('assignment_id'),
                'title': title, 'vocareum_course_id': str(course), 'vocareum_assignment_id': str(assignment),
                'vocareum_part_id': str(row.get('vocareum_part_id')), 'source_path': source_path,
                'origin': origin, 'sha256': hashlib.sha256(source).hexdigest(),
                'collected_at': datetime.now(timezone.utc).isoformat(),
                'file': str(target.relative_to(out))}
    info = folder / 'source.json'
    info.touch(mode=0o600)
    info.write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


def run(args):
    rows = read_rows(args.report)
    if args.limit:
        rows = rows[:args.limit]
    cached = cached_parts(args.archive_root, args.course)
    client = None
    remote = None
    results = []
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    for row in rows:
        pid = str(row.get('vocareum_part_id') or '').strip()
        label = f"{row.get('part_id')} {row.get('title', '')}"
        record = {'trellis_part_id': row.get('part_id'), 'title': row.get('title'), 'vocareum_part_id': pid}
        if not pid:
            record.update(status='unmapped', reason='No confirmed Vocareum part ID; match this placeholder separately.')
            print(f'[unmapped] {label}', flush=True)
            results.append(record)
            continue
        try:
            metadata, folder = cached.get(pid, ({}, None))
            source = None
            if folder is not None and not args.refresh:
                try:
                    source_path, source = cached_ferb(folder)
                    origin = 'existing_course_archive'
                except FileNotFoundError:
                    pass
            if source is None:
                if client is None:
                    token = os.environ.get('VOCAREUM_TOKEN') or args.token_file.read_text().strip()
                    if not token:
                        raise ValueError('The Vocareum token is empty.')
                    client = VocareumClient(token)
                if not metadata:
                    if remote is None:
                        print('Building the complete paginated Vocareum inventory...', flush=True)
                        remote = remote_parts(client, args.course)
                    metadata = remote.get(pid)
                    if metadata is None:
                        raise FileNotFoundError('Part not found after full course discovery.')
                source_path, source = download_ferb(client, args.course, metadata['assignment_id'], pid)
                origin = 'fresh_private_zip'
            record.update(save_source(args.out, row, source, source_path, args.course, metadata['assignment_id'], origin))
            record['status'] = 'saved'
            print(f'[saved] {label} ({origin})', flush=True)
        except requests.RequestException as exc:
            # Exception strings may contain signed URLs; record status/type only.
            status = exc.response.status_code if exc.response is not None else None
            record.update(status='error', reason=f'Vocareum request failed ({type(exc).__name__}, HTTP {status}).')
            print(f'[error] {label}: {record["reason"]}', flush=True)
        except (OSError, ValueError, RuntimeError, TimeoutError, BadZipFile) as exc:
            record.update(status='error', reason=str(exc))
            print(f'[error] {label}: {record["reason"]}', flush=True)
        results.append(record)
    summary = {key: sum(r['status'] == key for r in results) for key in ('saved', 'unmapped', 'error')}
    target = args.out / 'manifest.json'
    target.touch(mode=0o600)
    target.write_text(json.dumps({'vocareum_course_id': str(args.course), 'summary': summary, 'parts': results}, indent=2) + '\n')
    print(f"\nSaved {summary['saved']} | unmapped {summary['unmapped']} | errors {summary['error']}", flush=True)
    return 1 if summary['error'] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / 'var/ferb-sources')
    parser.add_argument('--course', default='144164')
    parser.add_argument('--archive-root', type=Path, default=ROOT / 'var/vocareum-coding-archives')
    parser.add_argument('--token-file', type=Path, default=ROOT.parent / 'token.txt')
    parser.add_argument('--refresh', action='store_true', help='Download fresh private ZIPs instead of using cached Ferb files.')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
