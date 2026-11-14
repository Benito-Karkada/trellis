"""Trusted scoring and feedback, implemented for CourseSpace.

Expected answers and scoring rules stay here. The executor receives source and
inputs only; it never receives a Case, expected answer, or sample solution.
"""
import ast
import math
import io
import json
import tokenize
from decimal import Decimal
from .spec import Exercise, Executor, RunRequest, valid_value
from .feedback import comparison


def equivalent(actual, expected, tolerance=None):
    # bool is a subclass of int in Python; do not accidentally accept True for 1.
    if type(actual) is bool or type(expected) is bool:
        return type(actual) is type(expected) and actual == expected
    if type(actual) in {int, float} and type(expected) in {int, float}:
        if any(type(value) is float and not math.isfinite(value) for value in (actual, expected)):
            return False
        return abs(actual - expected) <= tolerance if tolerance is not None else actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(equivalent(a, e, tolerance) for a, e in zip(actual, expected))
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equivalent(actual[k], v, tolerance) for k, v in expected.items())
    return actual == expected


def grade(source: str, exercise: Exercise, executor: Executor, *, operation="check", files=None, oracle_source=None, oracle_files=None, random_seed=None):
    exercise.validate()
    if operation not in {"check", "submit"}:
        raise ValueError("Plain Run does not grade or release solutions")
    checks = []
    try:
        if len(source.encode("utf-8")) > 256_000:
            raise ValueError("Source exceeds the supported size")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as error:
        location = f" on line {error.lineno}" if isinstance(error, SyntaxError) else ""
        checks.append({"id": "source", "passed": False, "message": f"Check your Python syntax{location}."})
        return result(checks, exercise, 0, operation)
    generated=[]
    if exercise.random_cases is not None:
        from .random_cases import expand
        count=exercise.random_cases["count"]
        exercise=expand(exercise,executor,oracle_source,oracle_files,random_seed)
        generated=exercise.cases[-count:]
    nodes = list(ast.walk(tree))
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    code_tokens = [(t.type, t.string) for t in tokens if t.type not in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}]
    def normalized_tokens(text):
        result=[]
        stream=tokenize.generate_tokens(io.StringIO(text).readline)
        collected=[]
        try:collected.extend(stream)
        except tokenize.TokenError:pass  # A required fragment may end with `close(`.
        for token in collected:
            if token.type in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}: continue
            value=token.string
            if token.type==tokenize.STRING:
                try:value=repr(ast.literal_eval(value))
                except (ValueError,SyntaxError):pass
            result.append((token.type,value))
        return result
    normalized=normalized_tokens(source)
    # Input declarations are supplied by the exercise; literal restrictions apply
    # to the student's implementation after those first declarations.
    protected=set().union(*(set(c.variables) for c in exercise.cases))
    ignored=set()
    for statement in tree.body:
        if isinstance(statement,(ast.Assign,ast.AnnAssign)):
            targets=statement.targets if isinstance(statement,ast.Assign) else [statement.target]
            names={t.id for t in targets if isinstance(t,ast.Name)}
            if names & protected:
                ignored.update(id(n) for n in ast.walk(statement));protected-=names
    constants=[n.value for n in nodes if isinstance(n,ast.Constant) and id(n) not in ignored]
    for rule in exercise.requirements:
        if rule.kind == "max_node_count":
            node,maximum=rule.target.split(":");found=sum(type(n).__name__==node for n in nodes)<=int(maximum)
        elif rule.kind == "require_nested_if":
            found = any(isinstance(outer, ast.If) and any(
                isinstance(inner, ast.If) and inner is not outer and inner.col_offset > outer.col_offset
                for inner in ast.walk(outer)) for outer in nodes)
        elif rule.kind == "require_function":
            found = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == rule.target for n in nodes)
        elif rule.kind in {"require_source","forbid_source"}:
            needle=normalized_tokens(rule.target)
            found=bool(needle) and any(normalized[i:i+len(needle)]==needle for i in range(len(normalized)))
        elif rule.kind == "require_comment":
            found=any(''.join(rule.target.split()) in ''.join(t.string.split()) for t in tokens if t.type==tokenize.COMMENT)
        elif rule.kind == "forbid_constant":
            expected=json.loads(rule.target)
            found=any(type(c) is type(expected) and c==expected for c in constants)
        else:
            found = any(type(n).__name__ == rule.target for n in nodes)
        passed = not found if rule.kind in {"forbid_node","forbid_source","forbid_constant"} else found
        checks.append({"id": rule.id, "passed": passed, "message": rule.message})

    earned = 0
    stopped = False
    for index, case in enumerate(exercise.cases, start=1):
        if stopped:
            checks.append({"id": case.id, "passed": False, "message": f"{case.label}: Not run because an earlier test exceeded a resource limit. Fix that issue and submit again."})
            continue
        request = RunRequest(source=source, action=case.action, target=case.target,
            arguments=case.arguments, stdin=case.stdin, seed=case.seed,
            timeout_seconds=exercise.timeout_seconds,files={**(files or {}),**case.files},variables=case.variables,steps=case.steps,argument_constructors=case.argument_constructors,clock=case.clock)
        try:
            observation = executor.run(request)
            if observation.status not in {"ok", "timeout", "runtime_error", "output_limit", "missing_target"}:
                # An unavailable executor must never become a student's zero grade.
                raise RuntimeError("Grading infrastructure is unavailable")
        except Exception as error:
            raise RuntimeError("Grading infrastructure is unavailable; retry this attempt") from error
        stopped = observation.status in {"timeout", "output_limit"}
        actual = observation.stdout if case.action in {"stdout","function_stdout"} else observation.value
        expected = case.expected
        if case.strip_output:
            actual, expected = actual.strip(), expected.strip() if isinstance(expected, str) else expected
        matches=equivalent(actual, expected, case.tolerance)
        if case.comparison=='python':
            if isinstance(actual,str) and isinstance(expected,str):matches=actual.strip()==expected.strip()
            elif type(actual)is float and type(expected)is float:matches=round(actual,4)==round(expected,4)
        if case.comparison=='contains' and isinstance(actual,str) and isinstance(expected,str):matches=expected in actual
        elif case.comparison=='whitespace' and isinstance(actual,str) and isinstance(expected,str):matches=''.join(actual.split())==''.join(expected.split())
        elif case.comparison=='string':matches=str(actual).strip()==str(expected).strip()
        elif case.comparison=='numeric_text':
            try:matches=abs(float(actual)-float(expected))<=0.005 and math.isfinite(float(actual))
            except (ValueError,TypeError,OverflowError):pass
        passed = observation.status == "ok" and valid_value(actual) and matches
        if passed:
            earned += case.weight
        label = case.label
        message = comparison(case, observation, passed)
        # Hints are explicitly student-facing author content, including for private tests.
        if not passed and case.hint:
            message += " " + case.hint
        checks.append({"id": case.id, "passed": passed, "message": f"{label}: {message}"})
    outcome=result(checks, exercise, earned, operation)
    if generated:outcome["random_inputs"]=[{"id":c.id,"arguments":c.arguments,"variables":c.variables} for c in generated]
    return outcome


def result(checks, exercise, earned, operation):
    passed = all(check["passed"] for check in checks)
    requirements_pass = all(check["passed"] for check in checks[:len(exercise.requirements)])
    fraction = Decimal(earned) / sum(case.weight for case in exercise.cases)
    if exercise.scoring == "all_or_nothing":
        fraction = Decimal(1 if passed else 0)
    elif not requirements_pass:
        fraction = Decimal(0)
    output = "\n\n".join(c['message'] for c in checks)
    return {"version": 1, "checks": checks, "score_fraction": str(fraction),
            "passed": passed, "preview": "All checks passed." if passed else "Some checks need attention.",
            "full_output": output, "workspace_files": {"full_results.txt": output + "\n"},
            "release_samples": operation == "submit" and passed}
