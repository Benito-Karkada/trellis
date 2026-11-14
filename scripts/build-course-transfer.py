"""Export course content only from local Compose; validate every referenced blob.

No accounts, Canvas connections, memberships, sessions, submissions, workspaces,
attempts, or progress are exported. Uses an existing private-media backup, and
refuses missing or altered activity files. Output belongs in ignored var/.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

MODELS = ("course", "lesson", "activity", "revision", "activityfile", "courseasset", "importrecord")
FOREIGN_KEYS = {
    "course": {"lti_registration_id"}, "lesson": {"course_id"},
    "activity": {"lesson_id", "published_revision_id"}, "revision": {"activity_id", "created_by_id"},
    "activityfile": {"revision_id"}, "courseasset": {"course_id"}, "importrecord": {"reviewer_id", "revision_id"},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", type=Path, default=Path("var/snapshot/private-media.tar.gz"))
    parser.add_argument("--output", type=Path, default=Path("var/azure-poc/course-transfer.tar.gz"))
    args = parser.parse_args()
    fixture, blobs, hashes = [], set(), {}
    for model in MODELS:
        sql = f"SELECT COALESCE(json_agg(t),'[]') FROM core_{model} t;"
        rows = json.loads(subprocess.check_output([
            "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "cs1301",
            "-d", "cs1301", "-At", "-c", sql,
        ]))
        for row in rows:
            pk = row.pop("id")
            fields = {key.removesuffix("_id") if key in FOREIGN_KEYS[model] else key: value for key, value in row.items()}
            if model == "course":
                fields["canvas_context_id"] = ""
                fields["lti_registration"] = None
            elif model == "revision":
                fields["created_by"] = None  # Target assigns an inactive content-import identity.
            elif model == "importrecord":
                fields["reviewer"] = None
            blob = fields.get("blob") or fields.get("source_archive")
            if blob:
                path = PurePosixPath(blob)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Unsafe source blob path")
                blobs.add(blob)
                if fields.get("sha256"):
                    if blob in hashes and hashes[blob] != fields["sha256"]:
                        raise ValueError("Conflicting blob digests")
                    hashes[blob] = fields["sha256"]
            fixture.append({"model": "core." + model, "pk": pk, "fields": fields})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.touch(mode=0o600)
    manifest = {}
    with tarfile.open(args.media, "r:gz") as source, tarfile.open(args.output, "w:gz") as target:
        for member in source:
            name = str(PurePosixPath(member.name))
            if name not in blobs:
                continue
            if not member.isfile():
                raise ValueError("Referenced blob is not a regular file")
            data = source.extractfile(member).read()
            digest = hashlib.sha256(data).hexdigest()
            if name in hashes and digest != hashes[name]:
                raise ValueError("Source file does not match stored hash: " + name)
            manifest[name] = {"sha256": digest, "size": len(data)}
            info = tarfile.TarInfo("blobs/" + name); info.size = len(data); info.mode = 0o600
            target.addfile(info, io.BytesIO(data))
        missing = blobs - manifest.keys()
        if missing:
            raise ValueError(f"Missing {len(missing)} referenced blobs")
        for name, value in (("course.json", fixture), ("manifest.json", manifest)):
            data = json.dumps(value).encode()
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o600
            target.addfile(info, io.BytesIO(data))
    print(json.dumps({"models": dict(Counter(r["model"] for r in fixture)), "blobs": len(manifest),
                      "archive_bytes": args.output.stat().st_size, "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))


if __name__ == "__main__":
    main()
