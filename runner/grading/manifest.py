"""Load private, declarative test data without importing course Python files."""
from dataclasses import fields
from .spec import Case, Exercise, Requirement


def load_definition(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Expected grading definition version 1")
    if set(data) - {"version", "cases", "requirements", "scoring", "timeout_seconds", "random_cases"}:
        raise ValueError("Unknown definition fields")
    def records(name, cls):
        values = data.get(name, [])
        if not isinstance(values, list):
            raise ValueError(f"Expected {name} list")
        allowed = {field.name for field in fields(cls)}
        result = []
        for value in values:
            if not isinstance(value, dict) or set(value) - allowed:
                raise ValueError(f"Invalid {name} fields")
            try:
                result.append(cls(**value))
            except TypeError as error:
                raise ValueError(f"Missing {name} fields") from error
        return tuple(result)
    exercise = Exercise(cases=records("cases", Case), requirements=records("requirements", Requirement),
                        scoring=data.get("scoring", "all_or_nothing"),
                        timeout_seconds=data.get("timeout_seconds", 2.0), random_cases=data.get("random_cases"))
    exercise.validate()
    return exercise
