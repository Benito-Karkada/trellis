"""Read-only single-part export; never execute the legacy download script."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import requests
from urllib.parse import urlencode, urlparse
from zipfile import ZipFile


def token_from_script(path):
    # This course's check.py reads token.txt beside itself. Read only that file;
    # never execute arbitrary code from the legacy utility.
    token_file = path.resolve().parent / 'token.txt'
    return token_file.read_text().strip()


def get(url, token=None):
    if urlparse(url).scheme != 'https':
        raise ValueError('HTTPS required')
    headers = {'Authorization': 'Token ' + token} if token else {}
    with requests.get(url, headers=headers, timeout=45, stream=True) as response:
        response.raise_for_status()
        chunks = []
        size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                raise ValueError('Download size limit exceeded')
            chunks.append(chunk)
        data = b''.join(chunks)
    if len(data) > 100 * 1024 * 1024:
        raise ValueError('Download size limit exceeded')
    return data


def extract(archive_path, destination):
    with ZipFile(archive_path) as archive:
        total = 0
        seen = set()
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            total += entry.file_size
            if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16) or total > 100 * 1024 * 1024
                    or path in seen):
                raise ValueError('Unsafe archive entry')
            seen.add(path)
        destination.mkdir(parents=True, exist_ok=False)
        archive.extractall(destination)
        return len(archive.infolist())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-script', type=Path)
    parser.add_argument('--token-file', type=Path, help='Defaults to token.txt in the parent course digest')
    parser.add_argument('--course', required=True)
    parser.add_argument('--assignment', required=True)
    parser.add_argument('--part', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    token_file = args.token_file or Path(__file__).resolve().parents[2] / 'token.txt'
    try:
        token = (token_file.read_text().strip() if args.token_file else
                 os.environ.get('VOCAREUM_TOKEN') or
                 (token_from_script(args.legacy_script) if args.legacy_script else token_file.read_text().strip()))
    except OSError:
        parser.error('Cannot read token.txt. Supply --token-file or VOCAREUM_TOKEN.')
    if not token: parser.error('The token is empty.')
    args.output.mkdir(parents=True, exist_ok=False)
    base = 'https://api.vocareum.com/api/v2'
    endpoint = f'{base}/courses/{args.course}/assignments/{args.assignment}/parts/{args.part}/files'
    manifest = {}
    for folder in ['startercode', 'scripts', 'private', 'docs', 'course']:
        try:
            result = json.loads(get(endpoint + '?' + urlencode({'dir': '/voc/' + folder}), token))
            transaction = result.get('transactionid')
            if not transaction:
                raise ValueError('No export transaction returned')
            for attempt in range(30):
                result = json.loads(get(f'{base}/transaction/{transaction}', token))
                if result.get('state') == 'success':
                    break
                if result.get('state') in ('failed', 'error'):
                    raise ValueError('Export transaction failed')
                time.sleep(2)
            else:
                raise TimeoutError('Export polling timed out')
            data = get(result['message'])  # Never forward the API token to storage.
            archive = args.output / (folder + '.zip')
            archive.write_bytes(data)
            count = extract(archive, args.output / folder)
            manifest[folder] = {'status': 'downloaded', 'files': count, 'sha256': hashlib.sha256(data).hexdigest()}
        except Exception as exc:
            # Exception messages may include signed URLs; print only exception type.
            manifest[folder] = {'status': 'failed', 'error_type': type(exc).__name__}
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                manifest[folder]['http_status'] = exc.response.status_code
        print(folder, manifest[folder], flush=True)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
