"""Parse the CS 1301 Kaltura CSV into safe native video references."""
from __future__ import annotations
import csv
import re
from dataclasses import dataclass
from io import StringIO

@dataclass(frozen=True)
class KalturaVideo:
    name: str
    partner_id: str
    uiconf_id: str
    entry_id: str
    widget_id: str | None

def load_kaltura_catalog(csv_text: str):
    videos, warnings = {}, []
    for row_number, row in enumerate(csv.DictReader(StringIO(csv_text.lstrip("\ufeff"))), start=2):
        name = (row.get("Video Name") or "").strip()
        embed = row.get("Kaltura Embed URL") or ""
        fields = {
            "partner_id": _match(r"/p/(\d+)/", embed),
            "uiconf_id": _match(r"uiconf_id/(\d+)", embed),
            "entry_id": _match(r"entry_id=([\w-]+)", embed),
            "widget_id": _match(r'widgetId["\']?:["\']([^"\']+)', embed),
        }
        if not name or not all(fields[k] for k in ("partner_id", "uiconf_id", "entry_id")):
            warnings.append({"code": "invalid_kaltura_row", "row": row_number, "name": name})
            continue
        if name in videos: warnings.append({"code": "duplicate_video_name", "row": row_number, "name": name})
        videos[name] = KalturaVideo(name=name, **fields)
    return videos, warnings

def _match(pattern, value):
    match = re.search(pattern, value)
    return match.group(1) if match else None
