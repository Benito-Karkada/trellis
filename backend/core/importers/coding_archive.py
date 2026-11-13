"""Separate, conservative import path for old Vocareum coding archives."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import PurePosixPath
from zipfile import ZipFile

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024

@dataclass(frozen=True)
class ArchiveFile:
    path: str
    visibility: str
    size: int

def inspect_zip(path):
    files, warnings = [], []
    total = 0
    with ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir(): continue
            normalized = PurePosixPath(info.filename)
            if normalized.is_absolute() or ".." in normalized.parts:
                warnings.append({"code": "unsafe_path", "path": info.filename})
                continue
            total += info.file_size
            if info.file_size > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
                warnings.append({"code": "size_limit", "path": info.filename})
                continue
            files.append(ArchiveFile(str(normalized), classify_path(normalized), info.file_size))
    if any(item.visibility == "quarantine" for item in files):
        warnings.append({"code": "unclassified_files"})
    return files, warnings

def classify_path(path):
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    # Directory scope wins over filenames: student sample files are placeholders,
    # while identically named private files hold unreleased solutions.
    if parts & {"course", "private", "scripts"}:
        return "staff" if name.startswith("sample_answer") else "grader"
    if "startercode" in parts:
        return "student"
    if name == "ferb.py" or "grader" in parts or "hidden_tests" in name:
        return "grader"
    if name.startswith("sample_answer") or "solution" in parts or "solution" in name:
        return "staff"
    if "starter" in parts or "student" in parts:
        return "student"
    return "quarantine"
