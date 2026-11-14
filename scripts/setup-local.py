#!/usr/bin/env python3
"""Create local configuration, start Compose, and load the full bundled course once."""
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not (ROOT / "course-data/cs1301.tar.gz").is_file():
        raise SystemExit("The full course bundle is missing. Pull the complete repository before running setup.")
    subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL, cwd=ROOT)
    path = ROOT / ".env"
    if not path.exists():
        text = (ROOT / ".env.example").read_text()
        text = text.replace("replace-with-a-random-local-secret", secrets.token_urlsafe(48))
        text = text.replace("replace-with-a-random-local-worker-secret", secrets.token_urlsafe(48))
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            output.write(text)
        print("Created private local configuration.", flush=True)
    else:
        print("Keeping existing local configuration.", flush=True)
    subprocess.run(["docker", "compose", "up", "-d", "--build", "--wait",
                    "postgres", "redis", "backend", "celery", "frontend"], check=True, cwd=ROOT)
    subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "manage.py",
                    "load_local_course", "/course-data/cs1301.tar.gz"],
                   check=True, cwd=ROOT)
    values = dict(line.split("=", 1) for line in path.read_text().splitlines()
                  if "=" in line and not line.lstrip().startswith("#"))
    port = os.environ.get("TRELLIS_FRONTEND_PORT", values.get("TRELLIS_FRONTEND_PORT", "5173"))
    print(f"\nTrellis is ready at http://localhost:{port}")
    print("Choose 'Open local instructor workspace' to explore the full CS 1301 course.")
    print("For coding Run/Submit, start the separate worker: sh scripts/start-worker.sh")


if __name__ == "__main__":
    main()
