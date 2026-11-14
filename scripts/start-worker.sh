#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker build -t cs1301-student-python:local runner/sandbox
exec .venv/bin/python -u runner/service.py
