#!/usr/bin/env python3
"""Download the six current CS 1301 programming quizzes from Vocareum.

Only the five Question parts in each assignment are included.  Vocareum's
scripts directory is intentionally excluded because this platform owns its
run and grading lifecycle.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path

from download_vocareum_coding_exercises import (
    DEFAULT_COURSE_ID,
    VocareumClient,
    atomic_json,
    error_record,
    export_folder,
    slug,
)

QUIZZES = {
    "5731588": "Programming Quiz 1",
    "5731590": "Programming Quiz 2",
    "5731592": "Programming Quiz 3",
    "5731345": "Programming Quiz 4",
    "5731521": "Programming Quiz 5",
    "5731535": "Programming Quiz 6",
}
FOLDERS = ("startercode", "private")


def discover(client: VocareumClient, course_id: str):
    inventory = []
    for assignment_id, assignment_name in QUIZZES.items():
        parts = client.parts(course_id, assignment_id)
        questions = [p for p in parts if str(p.get("name", "")).strip().casefold().startswith("question")]
        questions.sort(key=lambda p: int("".join(c for c in str(p.get("name", "")) if c.isdigit()) or 999))
        if len(questions) != 5:
            raise RuntimeError(f"{assignment_name} has {len(questions)} Question parts; expected 5")
        for position, part in enumerate(questions, 1):
            inventory.append({
                "assignment_id": assignment_id,
                "assignment_name": assignment_name,
                "part_id": str(part["id"]),
                "part_name": str(part.get("name") or f"Question {position}"),
                "position": position,
            })
    return inventory


def run(args):
    token = os.environ.get("VOCAREUM_TOKEN") or args.token_file.read_text().strip()
    if not token:
        raise SystemExit("The Vocareum token is empty")
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / ".download.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another programming quiz download is already running")
    client = VocareumClient(token, args.request_delay)
    inventory = discover(client, args.course)
    manifest = {"course_id": args.course, "quiz_count": len(QUIZZES), "question_count": len(inventory), "questions": inventory}
    atomic_json(args.output / "manifest.json", manifest)
    print(f"Found {len(inventory)} questions across {len(QUIZZES)} programming quizzes.", flush=True)
    failures = completed = 0
    for index, item in enumerate(inventory, 1):
        destination = args.output / f"{slug(item['assignment_name'])}--{item['assignment_id']}" / f"question-{item['position']}--{item['part_id']}"
        question_manifest_path = destination / "manifest.json"
        question_manifest = json.loads(question_manifest_path.read_text()) if question_manifest_path.exists() else {}
        question_manifest.update({"course_id": args.course, **item})
        print(f"[{index}/{len(inventory)}] {item['assignment_name']} / {item['part_name']}", flush=True)
        for folder in FOLDERS:
            prior = question_manifest.get("folders", {}).get(folder, {})
            if prior.get("status") == "downloaded" and (destination / folder).is_dir():
                print(f"  {folder}: already downloaded", flush=True)
                continue
            try:
                result = export_folder(client, args.course, item, folder, destination)
                print(f"  {folder}: {result['files']} files", flush=True)
            except Exception as exc:
                result = error_record(exc)
                failures += 1
                print(f"  {folder}: failed ({type(exc).__name__})", flush=True)
            question_manifest.setdefault("folders", {})[folder] = result
            atomic_json(question_manifest_path, question_manifest)
        if all(question_manifest.get("folders", {}).get(f, {}).get("status") == "downloaded" for f in FOLDERS):
            completed += 1
        manifest.update(completed_questions=completed, folder_failures_this_run=failures, last_processed_part_id=item["part_id"])
        atomic_json(args.output / "manifest.json", manifest)
    print(f"Finished: {completed}/{len(inventory)} questions complete; {failures} folder failures.", flush=True)
    return 0 if failures == 0 else 1


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", default=DEFAULT_COURSE_ID)
    parser.add_argument("--token-file", type=Path, default=project.parent / "token.txt")
    parser.add_argument("--output", type=Path, default=project / "var" / "vocareum-programming-quizzes")
    parser.add_argument("--request-delay", type=float, default=.15)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
