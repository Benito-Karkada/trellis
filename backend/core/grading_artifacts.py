"""Pure conversion contract; does not execute graders or mutate workspaces.

Call only with a result authenticated by the runner control plane. Private sample
contents must be loaded by the server after the release decision, not from a
student-supplied result or arbitrary output file.
"""
from decimal import Decimal


def feedback_update(results, *, operation, feedback=""):
    if operation not in {"run", "check", "submit"}:
        raise ValueError("Unknown operation")
    points = Decimal(str(results["points"]))
    if not points.is_finite() or not 0 <= points <= 5:
        raise ValueError("Expected points between zero and five")
    if not isinstance(results["full_output"], str) or not isinstance(feedback, str):
        raise ValueError("Expected text feedback")
    text = results["full_output"] + "\n"
    if feedback:
        text += "\n---\n\nHelpful feedback:\n" + feedback + "\n"
    return {
        "files": {"full_results.txt": text},
        "release_samples": operation == "submit" and points == 5 and results.get("show_samples") is True,
        # Preserve the supplied course's all-or-nothing policy explicitly.
        "score_fraction": "1" if points == 5 else "0",
    }
