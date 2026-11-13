"""Server-owned feedback files in learner workspaces."""
from pathlib import PurePosixPath

RESULTS_PLACEHOLDER = "Submit your code to see your test results here.\n"


def is_results_file(path):
    return PurePosixPath(path).name == "full_results.txt"


def with_results_placeholder(files):
    return {path: RESULTS_PLACEHOLDER if is_results_file(path) and not text.strip() else text
            for path, text in files.items()}


def results_unchanged(incoming, saved):
    return all(incoming.get(path) == text for path, text in saved.items() if is_results_file(path))
