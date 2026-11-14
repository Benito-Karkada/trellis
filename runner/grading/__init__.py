"""CourseSpace's first-party grading core. No legacy grader dependencies."""
from .engine import grade
from .spec import Case, Exercise, Requirement, RunRequest, Observation

__all__ = ["grade", "Case", "Exercise", "Requirement", "RunRequest", "Observation"]
