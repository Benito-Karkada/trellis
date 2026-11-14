#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Create the local virtual environment first: python3 -m venv .venv" >&2
  echo "Then install its dependencies: .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi
docker build -t cs1301-student-python:local runner/sandbox
exec .venv/bin/python -u runner/service.py
