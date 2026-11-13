"""Loss-aware edX problem parser producing native blocks plus private grading data."""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
import re
from uuid import uuid4

from defusedxml import ElementTree as ET

SUPPORTED_RESPONSES = {
    "multiplechoiceresponse", "choiceresponse", "optionresponse",
    "stringresponse", "numericalresponse",
}

@dataclass
class ImportCandidate:
    content: dict
    grading: dict
    warnings: list[dict]
    raw_xml: str

def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"

def _ungraded_poll(problem):
    """Recognize the export's constant-true survey without executing its script."""
    if problem.get("weight") not in {"0", "0.0"}:
        return False
    scripts = problem.findall("script")
    responses = problem.findall("customresponse")
    if len(scripts) != 1 or len(responses) != 1:
        return False
    try:
        tree = ast.parse(scripts[0].text or "")
    except SyntaxError:
        return False
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return False
    function = tree.body[0]
    return (function.name == responses[0].get("cfn") and not function.decorator_list
            and len(function.body) == 1 and isinstance(function.body[0], ast.Return)
            and isinstance(function.body[0].value, ast.Constant)
            and function.body[0].value.value is True
            and len(responses[0].findall("textline")) == 1)

def _rich(element, warnings):
    nodes = []
    def text(value):
        if value: nodes.append({"type": "text", "text": value})
    text(element.text)
    for child in element:
        tag = child.tag.lower()
        if tag in {"b", "strong"}:
            nodes.append({"type": "strong", "children": _rich(child, warnings)})
        elif tag in {"i", "em"}:
            nodes.append({"type": "emphasis", "children": _rich(child, warnings)})
        elif tag == "code" or (tag == "font" and "monospace" in child.get("style", "").lower()):
            nodes.append({"type": "inline_code", "text": "".join(child.itertext())})
        elif tag == "br":
            nodes.append({"type": "line_break"})
        elif tag == "a":
            nodes.append({"type": "link", "href": child.get("href", ""), "children": _rich(child, warnings)})
        elif tag == "img":
            nodes.append({"type":"image","src":child.get("src",""),"alt":child.get("alt","")})
        elif tag in {"ul","ol","li","table","thead","tbody","tr","td","th","h1","h2","h3","sub","sup","u"}:
            nodes.append({"type":"element","tag":tag,"children":_rich(child,warnings)})
        elif tag in {"script","style","solution","choicehint","optionhint"}:
            warnings.append({"code":"excluded_private_or_active_content","tag":tag})
        elif tag in {"p", "span", "div"}:
            nodes.extend(_rich(child, warnings))
        elif tag == "pre":
            nodes.append({"type": "element", "tag": "pre", "children": _rich(child, warnings)})
        else:
            warnings.append({"code": "unsupported_inline", "tag": tag})
            text("".join(child.itertext()))
        text(child.tail)
    return nodes

def _choice_content(choice, warnings):
    clone = ET.fromstring(ET.tostring(choice, encoding="unicode"))
    for hint in list(clone.findall("choicehint")):
        clone.remove(hint)
    return _rich(clone, warnings)

def _hint_content(element, warnings):
    """Remove edX's visible line-ending marker without changing Python examples."""
    nodes = _rich(element, warnings)

    def clean(items):
        for node in items:
            if node.get("children"):
                clean(node["children"])
            value = node.get("text")
            if node.get("type") == "text" and isinstance(value, str) and value.strip() != r"\n":
                node["text"] = re.sub(r"(?:\\n)+[ \t\r\n]*$", "", value)
        items[:] = [node for node in items if node.get("type") != "text" or node.get("text")]

    clean(nodes)
    return nodes

def parse_problem_xml(raw_xml: str) -> ImportCandidate:
    warnings = []
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        return ImportCandidate({"version": 1, "blocks": []}, {}, [{"code": "invalid_xml", "detail": str(exc)}], raw_xml)
    problem = root if root.tag == "problem" else root.find(".//problem")
    if problem is None:
        return ImportCandidate({"version": 1, "blocks": []}, {}, [{"code": "missing_problem"}], raw_xml)

    blocks = []
    grading = {"version": 1, "questions": {}}
    pending_label = None
    ungraded_poll = _ungraded_poll(problem)

    for child in problem:
        tag = child.tag.lower()
        if tag == "p":
            content = _rich(child, warnings)
            if content: blocks.append({"id": _id("p"), "type": "paragraph", "content": content})
        elif tag == "pre":
            blocks.append({"id": _id("code"), "type": "code", "language": "python", "text": "".join(child.itertext()).strip("\n")})
        elif tag == "label":
            pending_label = _rich(child, warnings)
        elif tag in SUPPORTED_RESPONSES:
            parsed = _parse_responses(child, pending_label or [], warnings)
            pending_label = None
            for block, private in parsed:
                blocks.append(block)
                grading["questions"][block["id"]] = private
        elif tag == "customresponse" and ungraded_poll:
            qid = _id("poll")
            blocks.append({"id": qid, "type": "fill_blank", "prompt": pending_label or [], "input": "text"})
            grading["questions"][qid] = {"accept_nonempty": True}
            pending_label = None
        elif tag == "solution":
            grading["solution"] = _rich(child, warnings)
        elif tag == "demandhint":
            hints = child.findall("hint")
            for hint in hints or [child]:
                grading.setdefault("hints", []).append(_hint_content(hint, warnings))
        elif tag == "problem":
            nested=copy.deepcopy(child);nested.tail=None
            candidate=parse_problem_xml(ET.tostring(nested,encoding="unicode"))
            blocks.extend(candidate.content["blocks"])
            grading["questions"].update(candidate.grading.get("questions",{}))
            grading.setdefault("hints", []).extend(candidate.grading.get("hints",[]))
            warnings.extend(candidate.warnings)
        elif tag == "description":
            blocks.append({"id":_id("description"),"type":"paragraph","content":_rich(child,warnings)})
        elif tag in {"hr","br"}:
            blocks.append({"id":_id("break"),"type":"document","content":[{"type":"element","tag":tag,"children":[]}]})
        elif tag in {"script","style"}:
            grading.setdefault("source_scripts", []).append(ET.tostring(child,encoding="unicode"))
            if not (tag == "script" and ungraded_poll):
                warnings.append({"code":"requires_dynamic_problem_review"})
        elif tag == "img":
            blocks.append({"id":_id("image"),"type":"document","content":[{"type":"image","src":child.get("src",""),"alt":child.get("alt","")}]})
        elif tag in {"table","ul","ol"}:
            blocks.append({"id":_id("document"),"type":"document","content":[{"type":"element","tag":tag,"children":_rich(child,warnings)}]})
        elif tag in {"font", "span", "div", "a"}:
            content = _rich(child, warnings)
            if content: blocks.append({"id": _id("p"), "type": "paragraph", "content": content})
        else:
            warnings.append({"code": "unsupported_element", "tag": tag})
            content = _rich(child, warnings)
            if content: blocks.append({"id": _id("p"), "type": "paragraph", "content": content})

        tail = (child.tail or "").strip()
        if tail:
            blocks.append({"id": _id("p"), "type": "paragraph", "content": [{"type": "text", "text": tail}]})

    if pending_label:
        warnings.append({"code": "orphan_label"})
        blocks.append({"id": _id("p"), "type": "paragraph", "content": pending_label})
    if not grading["questions"]:
        warnings.append({"code": "no_supported_responses"})
    return ImportCandidate({"version": 1, "blocks": blocks}, grading, _dedupe(warnings), raw_xml)

def _parse_responses(response, prompt, warnings):
    qid = _id("q")
    tag = response.tag.lower()
    if tag != "optionresponse":
        # Prompts frequently live inside response elements, before the inputs.
        # Strip answer-bearing nodes while keeping prose, labels, and code in order.
        wrapper = copy.deepcopy(response)
        private_tags = {"choicegroup", "checkboxgroup", "textline", "formulaequationinput",
                        "additional_answer", "responseparam", "solution", "script", "style"}
        for parent in wrapper.iter():
            for child in list(parent):
                if child.tag in private_tags:
                    parent.remove(child)
                elif child.tag == "label":
                    child.tag = "p"
        prompt = prompt + _rich(wrapper, warnings)
    if tag in {"multiplechoiceresponse", "choiceresponse"}:
        group_name = "choicegroup" if tag == "multiplechoiceresponse" else "checkboxgroup"
        group = response.find(group_name)
        choices, answers, hints, hint_rules = [], [], {}, {}
        if group is None: warnings.append({"code": "missing_choice_group", "tag": tag})
        for index, choice in enumerate(group.findall("choice") if group is not None else []):
            cid = f"{qid}_c{index + 1}"
            choices.append({"id": cid, "content": _choice_content(choice, warnings)})
            if choice.get("correct", "false").lower() in {"true", "1"}: answers.append(cid)
            hint = choice.find("choicehint")
            if hint is not None: hints[cid] = _hint_content(hint, warnings)
            hint_rules[cid] = [{"selected":h.get("selected", "true").lower() != "false", "content":_hint_content(h,warnings)} for h in choice.findall("choicehint")]
        kind = "multiple_choice" if tag == "multiplechoiceresponse" else "select_all"
        if kind == "multiple_choice" and not answers: warnings.append({"code": "invalid_correct_answer_count", "count": len(answers)})
        return [({"id": qid, "type": kind, "prompt": prompt, "choices": choices}, {"correct_choice_ids": answers, "selection":"one" if kind=="multiple_choice" else "all", "choice_feedback": hints, "choice_feedback_rules":hint_rules})]

    if tag == "optionresponse":
        results = []
        inline_prompt = []
        for child in response:
            if child.tag.lower() in {"p", "label", "description"}:
                inline_prompt.extend(_rich(child, warnings))
                continue
            if child.tag.lower() == "pre":
                inline_prompt.append({"type":"element", "tag":"pre", "children":_rich(child,warnings)})
                continue
            if child.tag.lower() != "optioninput":
                continue
            current_id = _id("q")
            choices, answers, hints = [], [], {}
            nested_options = child.findall("option")
            if nested_options:
                for index, option in enumerate(nested_options):
                    cid = f"{current_id}_c{index + 1}"
                    clone = ET.fromstring(ET.tostring(option, encoding="unicode"))
                    for option_hint in list(clone.findall("optionhint")):
                        clone.remove(option_hint)
                    choices.append({"id": cid, "content": _rich(clone, warnings)})
                    if option.get("correct", "false").lower() in {"true", "1"}: answers.append(cid)
                    option_hint = option.find("optionhint")
                    if option_hint is not None: hints[cid] = _hint_content(option_hint, warnings)
            else:
                try:
                    values = ast.literal_eval(child.get("options", "()"))
                except (SyntaxError, ValueError):
                    values = ()
                    warnings.append({"code": "invalid_options"})
                correct = child.get("correct", "")
                for index, value in enumerate(values if isinstance(values, (tuple, list)) else []):
                    cid = f"{current_id}_c{index + 1}"
                    choices.append({"id": cid, "content": [{"type": "text", "text": str(value)}]})
                    if str(value) == correct: answers.append(cid)
            question_prompt = prompt + inline_prompt if not results else inline_prompt
            results.append(({"id": current_id, "type": "multiple_choice", "prompt": question_prompt, "choices": choices}, {"correct_choice_ids": answers, "choice_feedback": hints}))
            inline_prompt = []
        if not results:
            warnings.append({"code": "missing_option_input"})
        return results

    answers = [response.get("answer", "")]
    answers.extend(a.get("answer", "") for a in response.findall("additional_answer"))
    textline = response.find("textline")
    size = 40
    if textline is not None:
        try:
            size = int(textline.get("size", 40))
        except (TypeError, ValueError):
            warnings.append({"code": "invalid_input_size", "value": textline.get("size")})
    input_config = {"size": size}
    if tag == "stringresponse":
        return [({"id": qid, "type": "fill_blank", "prompt": prompt, "input": input_config}, {"answers": answers, "case_sensitive": response.get("type", "ci") == "cs"})]
    tolerance = response.find("responseparam[@type='tolerance']")
    return [({"id": qid, "type": "numeric", "prompt": prompt, "input": input_config}, {"answers": answers, "tolerance": tolerance.get("default") if tolerance is not None else None})]

def _dedupe(items):
    result = []
    for item in items:
        if item not in result: result.append(item)
    return result
