"""Read-only audit of an unpacked CS 1301 edX/Vocareum migration source."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.importers.edx import parse_problem_xml
from core.importers.kaltura import load_kaltura_catalog
from core.importers.scope import include_section, scoped_xml_files
from core.schema import validate_content


class Command(BaseCommand):
    help = "Audit an unpacked course digest without modifying it or the database"

    def add_arguments(self, parser):
        parser.add_argument("source", type=Path)
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        source = options["source"].resolve()
        if not source.is_dir():
            raise CommandError(f"Source directory does not exist: {source}")

        report = self.audit(source)
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        if options["output"]:
            output = options["output"].resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
            self.stdout.write(f"Wrote {output}")
        self.stdout.write(rendered)

    def audit(self, source):
        problem_files = []
        video_files = []
        for path in scoped_xml_files(source):
            name = path.name.lower()
            if "problem - " in name:
                problem_files.append(path)
            elif "video - " in name:
                video_files.append(path)

        warning_counts = Counter()
        block_counts = Counter()
        invalid = []
        for path in problem_files:
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
            try:
                candidate = parse_problem_xml(raw)
            except Exception as exc:
                invalid.append({"path": str(path.relative_to(source)), "error": f"parser failure: {exc}"})
                continue
            for warning in candidate.warnings:
                warning_counts[warning["code"]] += 1
            for block in candidate.content["blocks"]:
                block_counts[block["type"]] += 1
            try:
                validate_content(candidate.content)
            except Exception as exc:
                invalid.append({"path": str(path.relative_to(source)), "error": str(exc)})

        catalog_path = source / "kaltura_videos.csv"
        catalog, catalog_warnings = ({}, [{"code": "missing_kaltura_catalog"}])
        if catalog_path.exists():
            catalog, catalog_warnings = load_kaltura_catalog(catalog_path.read_text(encoding="utf-8-sig"))

        matched = 0
        unmatched = []
        for path in video_files:
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
            name_match = re.search(r"\((\d+(?:\.\d+){3})\)", path.stem)
            if not name_match:
                name_match = re.search(r'display_name="[^"]*?((?:\d+\.){3}\d+)', raw)
            key = name_match.group(1) if name_match else None
            if key and key in catalog:
                matched += 1
            else:
                unmatched.append(str(path.relative_to(source)))

        return {
            "source": str(source),
            "included_sections": sorted(p.name for p in source.iterdir() if p.is_dir() and include_section(p.name)),
            "excluded_sections": sorted(p.name for p in source.iterdir() if p.is_dir() and re.match(r"^\d+\s+-\s+", p.name) and not include_section(p.name)),
            "problem_files": len(problem_files),
            "video_files": len(video_files),
            "native_block_counts": dict(sorted(block_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "invalid_content_documents": invalid,
            "kaltura_catalog_entries": len(catalog),
            "kaltura_catalog_warnings": catalog_warnings,
            "kaltura_matched_videos": matched,
            "kaltura_unmatched_count": len(unmatched),
            "kaltura_unmatched_examples": unmatched[:25],
        }
