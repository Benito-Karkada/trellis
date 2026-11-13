"""Versioned student-facing content validation and projection.

Answers, choice correctness, grader configuration, and hints live in Revision.grading.
They cannot leak through this projection by accidentally serializing a model.
"""
from django.core.exceptions import ValidationError

REQUIRED = {
    "paragraph": {"content"},
    "code": {"text", "language"},
    "multiple_choice": {"prompt", "choices"},
    "select_all": {"prompt", "choices"},
    "fill_blank": {"prompt", "input"},
    "numeric": {"prompt", "input"},
    "coding": {"prompt"},
    "kaltura": {"entry_id", "partner_id", "uiconf_id","widget_id"},
    "image": {"asset_id", "alt"},
    "document": {"content"},
    "video": {"url"},
    "placeholder": {"message"},
}

def _validate_rich(nodes):
    if not isinstance(nodes, list):
        raise ValidationError("Rich content must be a list")
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in {"text", "strong", "emphasis", "inline_code", "line_break", "link", "element", "image"}:
            raise ValidationError("Invalid rich-content node")
        if node["type"] == "image":
            if set(node) != {"type","src","alt"} or not all(isinstance(node[k],str) for k in ("src","alt")): raise ValidationError("Invalid image")
        elif node["type"] == "element":
            from .importers.rich_html import TAGS
            if set(node) != {"type","tag","children"} or node["tag"] not in TAGS: raise ValidationError("Invalid content element")
            _validate_rich(node["children"])
        elif node["type"] == "line_break":
            if set(node) != {"type"}: raise ValidationError("Invalid line break")
        elif node["type"] == "link":
            if set(node) != {"type", "href", "children"} or not isinstance(node["href"], str): raise ValidationError("Invalid link")
            _validate_rich(node["children"])
        elif node["type"] in {"strong", "emphasis"}:
            if set(node) != {"type", "children"}: raise ValidationError("Invalid formatting node")
            _validate_rich(node["children"])
        elif set(node) != {"type", "text"} or not isinstance(node["text"], str):
            raise ValidationError("Invalid text node")

def validate_content(content):
    if not isinstance(content, dict) or set(content) != {"version", "blocks"} or content["version"] != 1 or not isinstance(content["blocks"], list):
        raise ValidationError("Expected version 1 blocks document")
    for block in content["blocks"]:
        if not isinstance(block, dict) or block.get("type") not in REQUIRED:
            raise ValidationError("Unsupported block")
        fields = REQUIRED[block["type"]]
        if set(block) != fields | {"id", "type"} or not isinstance(block["id"], str):
            raise ValidationError("Invalid block fields")
        if block["type"] in {"paragraph","document"}: _validate_rich(block["content"])
        if "prompt" in fields: _validate_rich(block["prompt"])
        if block["type"] == "code" and not all(isinstance(block[k], str) for k in ("text", "language")): raise ValidationError("Invalid code block")
        if "choices" in fields:
            if not isinstance(block["choices"], list) or len(block["choices"]) < 2: raise ValidationError("Expected choices")
            for choice in block["choices"]:
                if not isinstance(choice, dict) or set(choice) != {"id", "content"} or not isinstance(choice["id"], str):
                    raise ValidationError("Invalid choice")
                _validate_rich(choice["content"])
    ids = [b["id"] for b in content["blocks"]]
    if len(ids) != len(set(ids)): raise ValidationError("Duplicate block id")

def student_projection(revision):
    validate_content(revision.content)
    return {"revision": revision.pk, "content": revision.content, "files": list(revision.files.filter(visibility="student").values("id", "path"))}
