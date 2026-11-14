#!/usr/bin/env python3
"""Download every current CS 1301 coding exercise from Vocareum.

Course 144164 is the source of truth. The course-digest LTI links are
intentionally ignored because they refer to the retired architecture.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import time
from typing import Any
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

import requests


BASE_URL = "https://api.vocareum.com/api/v2"
DEFAULT_COURSE_ID = "144164"
PART_FOLDERS = ("startercode", "scripts", "private")
SHARED_FOLDER = "course"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
EXCLUDED_ASSIGNMENT_TERMS = (
    "practice test",
    "practice quiz",
    "course information",
    "course surveys",
    "extra credit",
    "onboarding exam",
    "smartbook",
    "turtle",
    "working with vocareum",
)


def slug(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9.]+", "-", value).strip("-.")
    return value or "untitled"


def is_coding_part(title: str) -> bool:
    normalized = " ".join(title.casefold().split())
    # Current lessons use "Coding Exercise" while problem sets use "Coding Problem".
    # The latter includes the known check.py example, part 5591043.
    return "coding exercise" in normalized or "coding problem" in normalized


def include_assignment(title: str) -> bool:
    normalized = " ".join(title.casefold().split())
    if normalized.startswith("test -") or normalized.startswith("template -"):
        return False
    return not any(term in normalized for term in EXCLUDED_ASSIGNMENT_TERMS)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


class VocareumClient:
    def __init__(self, token: str, request_delay: float = 0.15):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Token " + token})
        self.request_delay = request_delay

    def _request(self, url: str, *, authenticated: bool = True, params=None, stream=False):
        if urlparse(url).scheme != "https":
            raise ValueError("Vocareum downloads must use HTTPS")
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                session = self.session if authenticated else requests
                response = session.get(url, params=params, timeout=60, stream=stream)
                if response.status_code == 429 or response.status_code >= 500:
                    response.close()
                    time.sleep(min(2**attempt, 30))
                    continue
                response.raise_for_status()
                if authenticated and self.request_delay:
                    time.sleep(self.request_delay)
                return response
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                time.sleep(min(2**attempt, 30))
        raise RuntimeError("Vocareum request failed after retries") from last_error

    def json(self, path: str, params=None) -> dict[str, Any]:
        with self._request(f"{BASE_URL}/{path.lstrip('/')}", params=params) as response:
            return response.json()

    def assignments(self, course_id: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        empty_pages = 0
        # This API returns ten rows even when per_page is twenty. Do not stop just
        # because a nonempty page is shorter than requested.
        for page in range(1, 501):
            rows = self.json(
                f"courses/{course_id}/assignments",
                {"page": page, "per_page": 20},
            ).get("assignments", [])
            if not rows:
                empty_pages += 1
                if empty_pages >= 2:
                    break
            else:
                empty_pages = 0
                for row in rows:
                    found[str(row["id"])] = row
        return list(found.values())

    def parts(self, course_id: str, assignment_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(100):
            result = self.json(
                f"courses/{course_id}/assignments/{assignment_id}/parts",
                {"page": page, "size": 100},
            )
            batch = result.get("parts", [])
            rows.extend(batch)
            if len(batch) < 100:
                break
        return rows

    def start_export(self, course_id: str, assignment_id: str, part_id: str, folder: str) -> str:
        result = self.json(
            f"courses/{course_id}/assignments/{assignment_id}/parts/{part_id}/files",
            {"dir": "/voc/" + folder},
        )
        transaction_id = result.get("transactionid")
        if not transaction_id:
            raise FileNotFoundError("No export transaction was returned")
        return str(transaction_id)

    def await_export(self, transaction_id: str) -> str:
        for _ in range(30):
            result = self.json(f"transaction/{transaction_id}")
            state = str(result.get("state", "")).casefold()
            if state == "success":
                url = str(result.get("message", ""))
                if urlparse(url).scheme != "https":
                    raise ValueError("Export completed without an HTTPS download URL")
                return url
            if state in {"failed", "error"}:
                raise RuntimeError("Vocareum export transaction failed")
            time.sleep(3)
        raise TimeoutError("Vocareum export transaction timed out")

    def download(self, url: str, destination: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        try:
            with self._request(url, authenticated=False, stream=True) as response:
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > MAX_ARCHIVE_BYTES:
                            raise ValueError("Archive exceeds the size limit")
                        digest.update(chunk)
                        output.write(chunk)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return size, digest.hexdigest()


def safe_extract(archive_path: Path, destination: Path) -> int:
    temporary = destination.with_name(destination.name + ".partial")
    shutil.rmtree(temporary, ignore_errors=True)
    try:
        with ZipFile(archive_path) as archive:
            seen: set[PurePosixPath] = set()
            extractable = []
            total = 0
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                total += entry.file_size
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or total > MAX_ARCHIVE_BYTES
                    or path in seen
                ):
                    raise ValueError("Unsafe archive entry")
                seen.add(path)
                # Vocareum's shared course directory contains a publicdata
                # symlink. Preserve the real files and omit links so an archive
                # can never write outside its destination when unpacked.
                if not stat.S_ISLNK(entry.external_attr >> 16):
                    extractable.append(entry)
            temporary.mkdir(parents=True)
            for entry in extractable:
                archive.extract(entry, temporary)
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)
        return len(extractable)
    except (BadZipFile, OSError, ValueError):
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def error_record(exc: Exception) -> dict[str, Any]:
    # Signed URLs and response bodies must never enter logs or manifests.
    record: dict[str, Any] = {"status": "failed", "error_type": type(exc).__name__}
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        record["http_status"] = exc.response.status_code
    return record


def discover(client: VocareumClient, course_id: str) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    assignments = sorted(client.assignments(course_id), key=lambda row: str(row.get("name", "")).casefold())
    for assignment in assignments:
        assignment_id = str(assignment["id"])
        assignment_name = str(assignment.get("name", "Untitled assignment"))
        if not include_assignment(assignment_name):
            continue
        for part in client.parts(course_id, assignment_id):
            part_name = str(part.get("name", "Untitled part"))
            if is_coding_part(part_name):
                inventory.append(
                    {
                        "assignment_id": assignment_id,
                        "assignment_name": assignment_name,
                        "part_id": str(part["id"]),
                        "part_name": part_name,
                    }
                )
    return inventory


def exercise_path(output: Path, item: dict[str, str]) -> Path:
    assignment = f"{slug(item['assignment_name'])}--{item['assignment_id']}"
    part = f"{slug(item['part_name'])}--{item['part_id']}"
    return output / "exercises" / assignment / part


def export_folder(
    client: VocareumClient,
    course_id: str,
    item: dict[str, str],
    folder: str,
    destination: Path,
) -> dict[str, Any]:
    archive = destination / "archives" / f"{folder}.zip"
    if archive.exists():
        size = archive.stat().st_size
        sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        file_count = safe_extract(archive, destination / folder)
        return {"status": "downloaded", "archive": str(archive.relative_to(destination)),
                "bytes": size, "files": file_count, "sha256": sha256}
    transaction_id = client.start_export(
        course_id, item["assignment_id"], item["part_id"], folder
    )
    download_url = client.await_export(transaction_id)
    size, sha256 = client.download(download_url, archive)
    file_count = safe_extract(archive, destination / folder)
    return {
        "status": "downloaded",
        "archive": str(archive.relative_to(destination)),
        "bytes": size,
        "files": file_count,
        "sha256": sha256,
    }


def run(args: argparse.Namespace) -> int:
    token = os.environ.get("VOCAREUM_TOKEN") or args.token_file.read_text().strip()
    if not token:
        raise SystemExit("The Vocareum token is empty")
    args.output.mkdir(parents=True, exist_ok=True)
    lock_file = (args.output / ".download.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another coding archive download is already running")

    client = VocareumClient(token, args.request_delay)
    print(f"Discovering coding exercises in Vocareum course {args.course}...", flush=True)
    inventory = discover(client, args.course)
    if args.assignment:
        inventory = [item for item in inventory if item["assignment_id"] in args.assignment]
    if args.limit is not None:
        inventory = inventory[: args.limit]

    root_manifest_path = args.output / "manifest.json"
    root_manifest: dict[str, Any] = {
        "course_id": args.course,
        "selection": "part title contains Coding Exercise or Coding Problem",
        "exercise_count": len(inventory),
        "exercises": inventory,
    }
    atomic_json(root_manifest_path, root_manifest)
    print(f"Found {len(inventory)} coding exercises.", flush=True)
    if args.plan_only or not inventory:
        print(f"Inventory saved to {root_manifest_path.resolve()}", flush=True)
        return 0

    # /voc/course is shared coursewide, so preserve one canonical copy rather
    # than downloading hundreds of identical Utility/Phineas archives.
    shared_destination = args.output / "shared"
    shared_manifest_path = shared_destination / "manifest.json"
    shared_manifest = (
        json.loads(shared_manifest_path.read_text()) if shared_manifest_path.exists() else {}
    )
    if not (
        shared_manifest.get(SHARED_FOLDER, {}).get("status") == "downloaded"
        and (shared_destination / SHARED_FOLDER).is_dir()
    ):
        try:
            print("Downloading shared course files...", flush=True)
            shared_manifest[SHARED_FOLDER] = export_folder(
                client, args.course, inventory[0], SHARED_FOLDER, shared_destination
            )
        except Exception as exc:
            shared_manifest[SHARED_FOLDER] = error_record(exc)
            print(f"Shared course files failed: {type(exc).__name__}", flush=True)
        atomic_json(shared_manifest_path, shared_manifest)

    completed = 0
    failures = 0
    for index, item in enumerate(inventory, 1):
        destination = exercise_path(args.output, item)
        manifest_path = destination / "manifest.json"
        manifest: dict[str, Any] = (
            json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        )
        manifest.update({"course_id": args.course, **item, "shared_course_files": "../../../shared/course"})
        print(
            f"[{index}/{len(inventory)}] {item['assignment_name']} / {item['part_name']}",
            flush=True,
        )
        for folder in PART_FOLDERS:
            prior = manifest.get("folders", {}).get(folder, {})
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
            manifest.setdefault("folders", {})[folder] = result
            atomic_json(manifest_path, manifest)
        if all(
            manifest.get("folders", {}).get(folder, {}).get("status") == "downloaded"
            for folder in PART_FOLDERS
        ):
            completed += 1
        root_manifest["completed_exercises"] = completed
        root_manifest["folder_failures_this_run"] = failures
        root_manifest["last_processed_part_id"] = item["part_id"]
        atomic_json(root_manifest_path, root_manifest)

    print(
        f"Finished: {completed}/{len(inventory)} exercises complete; "
        f"{failures} folder failures this run.",
        flush=True,
    )
    return 0 if failures == 0 else 1


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", default=DEFAULT_COURSE_ID)
    parser.add_argument(
        "--token-file",
        type=Path,
        default=project.parent / "token.txt",
        help="Defaults to token.txt beside the course digest; never copied to output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "var" / "vocareum-coding-archives",
    )
    parser.add_argument("--assignment", action="append", help="Limit to an assignment ID; repeatable")
    parser.add_argument("--limit", type=int, help="Limit exercises after discovery (for a smoke run)")
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except KeyboardInterrupt:
        print("Interrupted; rerun the same command to resume.", file=sys.stderr)
        raise SystemExit(130)
