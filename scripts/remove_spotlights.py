#!/usr/bin/env python3
"""Soft-delete imported Spotlight lessons/parts. Dry run by default; --apply removes matches."""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from clean_trailing_part_hyphens import pages
from upload_native_graders import API, private_json

ROOT = Path(__file__).resolve().parents[1]


def matches(row):
    return 'spotlight' in row['title'].casefold() or 'spotlight' in str(row.get('metadata', {}).get('group', '')).casefold()


def inventory(api, course):
    lessons = pages(api, f'/courses/{course}/assignments/?limit=200')
    parts = []
    for lesson in lessons:
        parts.extend(pages(api, f"/assignments/{lesson['id']}/parts/?limit=200"))
    return lessons, parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course', type=int, default=1)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    api = API(os.environ['TRELLIS_URL'], os.environ['TRELLIS_API_TOKEN'])
    report = ROOT / 'var/spotlight-cleanup' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        lessons, parts = inventory(api, args.course)
        selected_lessons = [l for l in lessons if matches(l)]
        lesson_ids = {l['id'] for l in selected_lessons}
        selected_parts = [p for p in parts if matches(p)]
        groups = [p for p in parts if 'spotlight' in str(p.get('metadata', {}).get('group', '')).casefold() and not matches(p)]
        plan = {'course_id': args.course, 'lessons': selected_lessons, 'parts': selected_parts,
                'parts_inside_deleted_lessons': [p for p in parts if p['assignment_id'] in lesson_ids],
                'group_only_matches': groups, 'original_lessons': lessons, 'original_parts': parts}
        private_json(report / 'plan.json', plan)
        print(f"Scanned {len(lessons)} lessons and {len(parts)} parts. Matched {len(selected_lessons)} lessons and {len(selected_parts)} parts.", flush=True)
        for kind, rows in [('Lesson', selected_lessons), ('Part', selected_parts)]:
            for row in rows: print(f"{kind} {row['id']}: {row['title']}", flush=True)
        for row in groups: print(f"Group-only match {row['id']}: {row['title']} [{row['metadata']['group']}]", flush=True)
        print('Saved plan:', report, flush=True)
        if not args.apply: return
        applied = []
        # Delete matching parts before their parent lessons, retaining all underlying records.
        for row in selected_parts:
            path = f"/parts/{row['id']}/"
            current = api.request('GET', path)
            if current['title'] != row['title'] or not matches(current):
                raise RuntimeError(f"Part changed while preparing removal: {row['id']}")
            api.request('DELETE', path, {}, revision=current['revision_id'])
            applied.append({'kind': 'part', 'id': row['id'], 'title': row['title']})
            private_json(report / 'applied.json', applied)
            if len(applied) % 10 == 0: print(f'Removed {len(applied)} matching parts.', flush=True)
        for row in selected_lessons:
            path = f"/assignments/{row['id']}/"
            current = api.request('GET', path)
            if current['title'] != row['title'] or not matches(current):
                raise RuntimeError(f"Lesson changed while preparing removal: {row['id']}")
            api.request('DELETE', path, {})
            applied.append({'kind': 'lesson', 'id': row['id'], 'title': row['title']})
            private_json(report / 'applied.json', applied)
        remaining_lessons, remaining_parts = inventory(api, args.course)
        assert not any(matches(l) for l in remaining_lessons)
        assert not any(matches(p) for p in remaining_parts)
        removed_parts = {p['id'] for p in selected_parts} | {p['id'] for p in parts if p['assignment_id'] in lesson_ids}
        assert {p['id'] for p in remaining_parts} == {p['id'] for p in parts} - removed_parts
        assert {l['id'] for l in remaining_lessons} == {l['id'] for l in lessons} - lesson_ids
        private_json(report / 'result.json', {'status': 'verified', 'removed_lessons': len(selected_lessons),
            'removed_parts': len(removed_parts), 'remaining_lessons': len(remaining_lessons), 'remaining_parts': len(remaining_parts)})
        print(f"Verified removal: {len(selected_lessons)} lessons and {len(removed_parts)} parts. All unrelated items remain.", flush=True)
    finally:
        api.session.close()


if __name__ == '__main__':
    main()
