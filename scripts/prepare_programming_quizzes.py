#!/usr/bin/env python3
"""Translate downloaded quiz sources into Trellis grading definitions.

The legacy Ferb modules are parsed only to identify inputs. Expected answers
are observed from staff sample answers inside the same isolated Python image
used for student submissions; legacy grader code is never imported or run.
"""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runner"))
from grading.docker_executor import DockerExecutor
from grading.spec import RunRequest


def assignments(tree):
    values = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try: values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError): pass
    return values


def call_name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return node.attr
    return ""


def variable_type_definition(tree):
    """Recognize literal type assertions, without evaluating legacy Python.

Values are deliberately unconstrained: a variable-type exercise must accept
any value of the specified exact built-in type, not only the staff example.
"""
    nodes = list(ast.walk(tree))
    names = {call_name(n.func) for n in nodes if isinstance(n, ast.Call)}
    if "type" not in names or not any(isinstance(n, ast.Attribute) and n.attr == "global_variables" for n in nodes):
        return None
    declaration = next((n.value for n in nodes if isinstance(n, ast.Assign) and
                        any(isinstance(t, ast.Name) and t.id == "expected_variables" for t in n.targets)), None)
    output = assignments(tree).get("correct_output")
    if not isinstance(declaration, (ast.List, ast.Tuple)) or not declaration.elts or not isinstance(output, str):
        return None
    supported = {"int", "float", "str", "bool", "list", "dict", "tuple", "set"}
    translated = []
    targets = set()
    for pair in declaration.elts:
        if not isinstance(pair, (ast.List, ast.Tuple)) or len(pair.elts) != 2:
            return None
        target, expected = pair.elts
        if (not isinstance(target, ast.Constant) or not isinstance(target.value, str)
                or not target.value.isidentifier() or not isinstance(expected, ast.Name)
                or expected.id not in supported):
            return None
        if target.value in targets:
            return None
        targets.add(target.value)
        translated.append({"id": "type-" + target.value, "label": "Type of " + target.value,
                           "action": "variable_type", "target": target.value,
                           "expected": expected.id, "public": True})
    translated.append({"id": "output", "label": "Printed types", "action": "stdout",
                       "expected": output, "strip_output": "strip" in names, "public": True})
    return {"version": 1, "scoring": "all_or_nothing", "cases": translated}


def prepare(question: Path, executor):
    ferb_path = question / "private" / "Ferb.py"
    tree = ast.parse(ferb_path.read_text())
    values = assignments(tree)
    cases = values.get("test_cases", values.get("cases"))
    function_name = values.get("student_function_name")
    variable_names = values.get("parameter_names", values.get("var_names", []))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    call_names = {call_name(node.func) for node in calls}
    action = "function" if "check_function_test_cases" in call_names else "stdout" if "check_printed_test_cases" in call_names else None
    grader_call = next((node for node in calls if call_name(node.func) in {"check_function_test_cases","check_printed_test_cases"}), None)
    if grader_call:
        try:
            variable_names = variable_names or ast.literal_eval(grader_call.args[0])
            cases = cases or ast.literal_eval(grader_call.args[1])
            if action == "function" and not function_name: function_name = ast.literal_eval(grader_call.args[3])
        except (ValueError, TypeError, IndexError): pass
    student_files = [p for p in (question / "startercode").iterdir() if p.is_file() and p.suffix == ".py"]
    type_definition = variable_type_definition(tree)
    if type_definition and student_files:
        (question / "definition.json").write_text(json.dumps(type_definition, indent=2) + "\n")
        return {"status": "ready", "entrypoint": student_files[0].name, "cases": len(type_definition["cases"])}
    if student_files and student_files[0].name in {"Book.py","Playlist.py","Library.py"}:
        definitions = {
            "Book.py": [(list(case), [{"op":"attribute","name":"title"},{"op":"attribute","name":"pages"},{"op":"call","name":"description","arguments":[]}], [case[0],case[1],f"{case[0]} has {case[1]} pages."]) for case in [("Dune",412),("Coraline",176),("It",1138)]],
            "Playlist.py": [(["Road Trip"],[{"op":"call","name":"add_song","arguments":["Song A"]},{"op":"call","name":"add_song","arguments":["Song B"]},{"op":"attribute","name":"name"},{"op":"attribute","name":"songs"}],[1,2,"Road Trip",["Song A","Song B"]])],
            "Library.py": [( [titles], [{"op":"attribute","name":"titles"},{"op":"call","name":"has_title","arguments":[title]}], [titles,expected]) for titles,title,expected in [(["Dune","Coraline","Beloved"],"Coraline",True),(["Dune","Coraline","Beloved"],"Dracula",False),(["One"],"One",True),(["One"],"Two",False)]],
        }
        target = student_files[0].stem
        translated = [{"id":f"case-{i}","label":f"Test {i}","action":"scenario","target":target,
            "arguments":args,"steps":steps,"expected":expected,"public":True} for i,(args,steps,expected) in enumerate(definitions[student_files[0].name],1)]
        (question / "definition.json").write_text(json.dumps({"version":1,"scoring":"all_or_nothing","cases":translated},indent=2)+"\n")
        return {"status":"ready","entrypoint":student_files[0].name,"cases":len(translated)}
    solution = question / "private" / "sample_answer_1.py"
    if not cases or not student_files or action is None:
        return {"status":"needs_review", "reason":"Could not derive isolated tests from the archive."}
    solution_source = solution.read_text(errors="replace") if solution.exists() else ""
    oracle_name = ""
    if not solution_source:
        oracle = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in {"correct_function","correct"}), None)
        if oracle is None: return {"status":"needs_review", "reason":"No staff answer or declarative answer function was found."}
        oracle_name = oracle.name
        solution_source = ast.unparse(oracle) + "\n"
    translated = []
    fixture_files = {}
    # Capture small text fixtures created by legacy test setup.
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            try:
                value = ast.literal_eval(node)
                if isinstance(value, dict) and value and all(isinstance(k,str) and isinstance(v,str) for k,v in value.items()):
                    if all(k.endswith((".txt",".csv")) for k in value): fixture_files.update(value)
            except (ValueError,TypeError): pass
    for index, raw in enumerate(cases, 1):
        args = list(raw) if isinstance(raw, tuple) else [raw]
        variables = dict(zip(variable_names, args)) if action == "stdout" else {}
        oracle_action = "function" if oracle_name else action
        oracle_arguments = (tuple(args),) if oracle_name else tuple(args)
        observation = executor.run(RunRequest(source=solution_source, action=oracle_action,
            target=oracle_name or function_name or "", arguments=oracle_arguments, variables=variables, files=fixture_files))
        expected = (str(observation.value) + "\n") if oracle_name and action == "stdout" else observation.stdout if action == "stdout" else observation.value
        if observation.status != "ok":
            return {"status":"needs_review", "reason":f"Staff answer failed isolated case {index}: {observation.status}"}
        translated.append({"id":f"case-{index}","label":f"Test {index}","action":action,
            "target":function_name or "","arguments":args,"variables":variables,"expected":expected,"public":True})
    definition = {"version":1,"scoring":"all_or_nothing","cases":translated}
    (question / "definition.json").write_text(json.dumps(definition, indent=2) + "\n")
    return {"status":"ready","entrypoint":student_files[0].name,"cases":len(translated)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "var" / "vocareum-programming-quizzes")
    parser.add_argument("--glob", default="programming-quiz-*--*/question-*--*/manifest.json")
    parser.add_argument("--report", default="translation-report.json")
    args = parser.parse_args()
    root = args.root.resolve()
    executor = DockerExecutor()
    report = {}
    for manifest in sorted(root.glob(args.glob)):
        question = manifest.parent
        result = prepare(question, executor)
        report[str(question.relative_to(root))] = result
        print(f"{question.parent.name} / {question.name}: {result['status']}", flush=True)
    (root / args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(f"Prepared {sum(v['status']=='ready' for v in report.values())}/{len(report)} questions.")


if __name__ == "__main__": main()
