"""Course-owned visualization examples, authored through the browser."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .course_context import current_membership
from .models import VisualizationSandbox
from .studio import json_body
from .visualization import access


def context(request, *, write=False):
    access(request)
    member = current_membership(request)
    can_edit = (member.role == "instructor"
        and request.session.get("student_view_course") != member.course_id)
    if write and not can_edit:
        raise PermissionDenied("Only course instructors can save visualization sandboxes.")
    return member, can_edit


def data(sandbox):
    return {"id": sandbox.pk, "title": sandbox.title, "sandbox_name": sandbox.sandbox_name,
        "description": sandbox.description, "source": sandbox.source, "version": sandbox.version}


@require_GET
def library(request):
    member, can_edit = context(request)
    rows = VisualizationSandbox.objects.filter(course=member.course).order_by("title", "pk")
    return JsonResponse({"can_edit": can_edit, "sandboxes": [data(row) for row in rows]})


def validated(payload, *, update=False):
    fields = {"title", "sandbox_name", "description", "source"}
    if set(payload) != fields | ({"version"} if update else set()):
        raise ValueError("Include a title, sandbox name, description, and Python code.")
    cleaned = {}
    for field, maximum in [("title", 160), ("sandbox_name", 100), ("description", 1000)]:
        value = payload[field]
        if not isinstance(value, str) or len(value.strip()) > maximum or (field != "description" and not value.strip()):
            raise ValueError(f"Enter a valid {field.replace('_', ' ')} (up to {maximum} characters).")
        cleaned[field] = value.strip()
    source = payload["source"]
    if (not isinstance(source, str) or not source.strip() or len(source.encode()) > 12000
            or len(source.splitlines()) > 300):
        raise ValueError("Use a Python program up to 300 lines and 12 KB.")
    cleaned["source"] = source
    if update and (type(payload["version"]) is not int or payload["version"] < 1):
        raise ValueError("Include the current sandbox version.")
    return cleaned


@require_POST
@json_body
@transaction.atomic
def create(request):
    member, _ = context(request, write=True)
    try:
        fields = validated(request.payload)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    sandbox = VisualizationSandbox.objects.create(course=member.course, created_by=request.user, **fields)
    return JsonResponse({"sandbox": data(sandbox)}, status=201)


@require_POST
@json_body
@transaction.atomic
def update(request, pk):
    member, _ = context(request, write=True)
    sandbox = get_object_or_404(VisualizationSandbox.objects.select_for_update(), pk=pk, course=member.course)
    try:
        fields = validated(request.payload, update=True)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if request.payload["version"] != sandbox.version:
        return JsonResponse({"error": "This sandbox changed in another tab. Reload it before saving."}, status=409)
    for field, value in fields.items():
        setattr(sandbox, field, value)
    sandbox.version += 1
    sandbox.save()
    return JsonResponse({"sandbox": data(sandbox)})
