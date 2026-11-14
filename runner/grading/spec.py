"""Private exercise rules and the public request sent to an isolated executor."""
from dataclasses import dataclass, field
from typing import Any, Protocol
try:
    from trellis_contract import validate_random_cases,validate_fixture_path,validate_constructors,validate_trace,validate_observation_expected
except ModuleNotFoundError:
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))
    from core.grading_contract import validate_random_cases,validate_fixture_path,validate_constructors,validate_trace,validate_observation_expected


def valid_value(value):
    """Bound observations before comparing data originating in a sandbox."""
    import math
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 20 or count > 10000:
            return False
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                return False
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) in {list, tuple}:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is int:
            if item.bit_length() > 4096:
                return False
        elif type(item) is float:
            if not math.isfinite(item):
                return False
        elif type(item) is str:
            if len(item) > 65536:
                return False
        elif item is not None and type(item) is not bool:
            return False
    return True


@dataclass(frozen=True)
class RunRequest:
    source: str
    action: str = "module"
    target: str = ""
    arguments: tuple = ()
    stdin: str = ""
    seed: int = 0
    timeout_seconds: float = 2.0
    files: dict = field(default_factory=dict)
    variables: dict = field(default_factory=dict)
    steps: tuple = ()
    argument_constructors: dict = field(default_factory=dict)
    clock: str | None = None


@dataclass(frozen=True)
class Observation:
    status: str  # ok, timeout, runtime_error, output_limit, infrastructure_error
    value: Any = None
    stdout: str = ""


class Executor(Protocol):
    def run(self, request: RunRequest) -> Observation:
        """Use a fresh isolated process. Never evaluate the source in the supervisor."""
        ...


@dataclass(frozen=True)
class Case:
    id: str
    label: str
    expected: Any
    action: str = "variable"  # variable, function, stdout
    target: str = ""
    arguments: tuple = ()
    stdin: str = ""
    seed: int = 0
    tolerance: float | None = None
    weight: int = 1
    public: bool = True
    hint: str = ""
    variables: dict = field(default_factory=dict)
    steps: tuple = ()
    strip_output: bool = False
    comparison: str = "exact"
    files: dict = field(default_factory=dict)
    argument_constructors: dict = field(default_factory=dict)
    clock: str | None = None


@dataclass(frozen=True)
class Requirement:
    id: str
    kind: str  # require_node, forbid_node, require_function
    target: str
    message: str


@dataclass(frozen=True)
class Exercise:
    cases: tuple[Case, ...]
    requirements: tuple[Requirement, ...] = ()
    scoring: str = "all_or_nothing"
    timeout_seconds: float = 2.0
    random_cases: dict | None = None

    def validate(self):
        import ast
        import math
        if not self.cases or len(self.cases) > 200:
            raise ValueError("Exercises need 1–200 cases")
        if self.scoring not in {"all_or_nothing", "weighted"}:
            raise ValueError("Unknown scoring policy")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("Invalid timeout")
        if self.random_cases is not None:
            validate_random_cases(self.random_cases,len(self.cases))
            if any(c.id.startswith("random-") for c in self.cases):raise ValueError("The random- case ID prefix is reserved")
        ids = [case.id for case in self.cases] + [rule.id for rule in self.requirements]
        if any(not isinstance(id, str) or not id for id in ids) or len(ids) != len(set(ids)):
            raise ValueError("Case and requirement IDs must be unique")
        for case in self.cases:
            if (type(case.public) is not bool or not isinstance(case.label, str)
                or not isinstance(case.hint, str) or not isinstance(case.stdin, str)
                or type(case.seed) is not int):
                raise ValueError("Invalid case fields")
            if not valid_value(case.expected) or not valid_value(case.arguments) or not valid_value(case.variables) or not valid_value(case.steps):
                raise ValueError("Unsupported or oversized test values")
            if any(not key.isidentifier() for key in case.variables):
                raise ValueError("Test variable names must be Python identifiers")
            if not isinstance(case.files,dict) or len(case.files)>20 or not valid_value(case.files) or any(not isinstance(text,str) for text in case.files.values()):raise ValueError('Invalid fixture files')
            for path in case.files:validate_fixture_path(path)
            validate_constructors(case.argument_constructors,len(case.arguments))
            if case.clock is not None:
                import datetime
                if not isinstance(case.clock,str):raise ValueError('Clock must be an ISO datetime.')
                datetime.datetime.fromisoformat(case.clock)
            if case.action not in {"variable", "variable_type", "function", "stdout", "file", "scenario", "trace", "function_file", "function_stdout", "recursion", "module_outcome"}:
                raise ValueError("Unsupported action")
            if type(case.strip_output) is not bool or (case.strip_output and case.action not in {"stdout","function_stdout"}):
                raise ValueError("Output stripping is only supported for stdout cases")
            if case.comparison not in {"exact","contains","numeric_text","string","whitespace","python"}:raise ValueError("Invalid comparison mode")
            if case.strip_output and not isinstance(case.expected, str):
                raise ValueError("Normalized stdout must expect a string")
            if case.action == "variable_type" and (not isinstance(case.expected, str) or case.expected not in {"int", "float", "str", "bool", "list", "dict", "tuple", "set", "NoneType"}):
                raise ValueError("Expected a supported built-in type")
            if case.action == "trace":validate_trace(case.steps)
            validate_observation_expected(case.action,case.steps,case.expected)
            if case.action == "scenario":
                if any(type(step) is not dict or step.get("op") not in {"attribute","call"}
                       or not isinstance(step.get("name"), str) or not step["name"].isidentifier()
                       for step in case.steps):
                    raise ValueError("Invalid class scenario")
            if type(case.weight) is not int or case.weight <= 0:
                raise ValueError("Weights must be positive integers")
            if case.action == "file":
                from pathlib import PurePosixPath
                path = PurePosixPath(case.target)
                if not case.target or path.is_absolute() or ".." in path.parts or "\\" in case.target:
                    raise ValueError("Expected a relative file path")
            elif case.action not in {"stdout","function_stdout"} and not case.target.isidentifier():
                raise ValueError("Expected a Python identifier")
            if case.tolerance is not None and (not math.isfinite(case.tolerance) or case.tolerance < 0):
                raise ValueError("Invalid numeric tolerance")
        for rule in self.requirements:
            if not isinstance(rule.target, str) or not isinstance(rule.message, str):
                raise ValueError("Invalid requirement fields")
            if rule.kind not in {"require_node", "forbid_node", "require_function", "require_source", "forbid_source", "forbid_constant", "require_comment", "max_node_count", "require_nested_if"}:
                raise ValueError("Unsupported source requirement")
            if rule.kind=='max_node_count':
                node,maximum=rule.target.split(':')
                if not 0<=int(maximum)<=100 or not isinstance(getattr(ast,node,None),type):raise ValueError('Invalid syntax count limit')
            if rule.kind in {"require_node", "forbid_node"}:
                node_type = getattr(ast, rule.target, None)
                if not isinstance(node_type, type) or not issubclass(node_type, ast.AST):
                    raise ValueError("Unknown Python syntax node")
