"""Local execution-host CLI. Private definitions are never mounted into sandboxes."""
import argparse
import json
from pathlib import Path
from .docker_executor import DockerExecutor
from .engine import grade
from .manifest import load_definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--operation", choices=["check", "submit"], default="check")
    parser.add_argument("--image", default="cs1301-student-python:local")
    args = parser.parse_args()
    try:
        exercise = load_definition(json.loads(args.definition.read_text()))
        result = grade(args.source.read_text(), exercise, DockerExecutor(args.image), operation=args.operation)
    except Exception:
        # Do not print private definitions, source, credentials, or exception payloads.
        parser.exit(2, "Grading could not complete. Check the private definition and executor setup. No score was recorded.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
