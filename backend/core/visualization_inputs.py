"""Build visible sample walkthroughs from public inputs, never expected answers.

This module parses Python but does not execute it. The generated program is
returned to the student and the exact same program is sent to the sandbox.
"""
import ast


def literal(value, depth=0):
    if depth > 12:
        raise ValueError("Input is too deeply nested")
    if type(value) in (str, int, float, bool, type(None)):
        return repr(value)
    if type(value) is list:
        return "[" + ", ".join(literal(item, depth+1) for item in value) + "]"
    if type(value) is dict:
        if any(isinstance(key, str) and key.startswith("$") for key in value):
            if set(value) == {"$tuple"}:
                return "(" + ", ".join(literal(item, depth+1) for item in value["$tuple"]) + ",)" if value["$tuple"] else "()"
            if set(value) == {"$set"}:
                return "{" + ", ".join(literal(item, depth+1) for item in value["$set"]) + "}" if value["$set"] else "set()"
            raise ValueError("This input needs a specialized fixture")
        return "{" + ", ".join(literal(key, depth+1) + ": " + literal(item, depth+1) for key, item in value.items()) + "}"
    raise ValueError("Unsupported input")


def public_cases(revision):
    result = []
    for case in revision.grading.get("definition", {}).get("cases", []):
        if not case.get("public", True) or case.get("action") not in {"stdout", "function", "function_stdout", "variable", "variable_type"}:
            continue
        if case.get("argument_constructors") or case.get("files") or case.get("clock"):
            continue
        if case.get("action") in {"function", "function_stdout"} and not str(case.get("target", "")).isidentifier():
            continue
        try:
            literal(case.get("arguments", []))
            for name, value in case.get("variables", {}).items():
                if not name.isidentifier():
                    raise ValueError("Invalid variable")
                literal(value)
        except (ValueError, TypeError, RecursionError):
            continue
        result.append(case)
        if len(result) >= 20:
            break
    return result


def select_case(revision, selected=None):
    cases = public_cases(revision)
    if selected == "original":
        return None
    if selected is None:
        return cases[0] if cases else None
    case = next((case for case in cases if case["id"] == selected), None)
    if case is None:
        raise ValueError("That public test input is unavailable")
    return case


def walkthrough(source, case):
    if case is None:
        return source
    variables = dict(case.get("variables", {}))
    tree = ast.parse(source)
    # Match grading's replaceable module-level inputs, preserving all other
    # statements. The displayed code includes the replacement values explicitly.
    body = []
    for statement in tree.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if names and all(isinstance(target, ast.Name) for target in targets) and any(name in variables for name in names):
            for name in names:
                expression = ast.parse(literal(variables.pop(name)), mode="eval").body if name in variables else statement.value
                body.append(ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=expression))
        else:
            body.append(statement)
    tree.body = [ast.parse(f"{name} = {literal(value)}").body[0] for name, value in variables.items()] + body
    ast.fix_missing_locations(tree)
    source = ast.unparse(tree)
    if case["action"] in {"function", "function_stdout"}:
        arguments = ", ".join(literal(value) for value in case.get("arguments", []))
        call = f"{case['target']}({arguments})"
        if case["action"] == "function":
            call = f"print({call})"
        source += "\n\n# Run with this public test input.\n" + call
    return source + "\n"
