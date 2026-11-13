"""Browser-managed course outline mutations for teaching staff."""
import hashlib
import json
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST, require_GET

from .course_settings import staff_course
from .models import Activity, ActivityFile, Lesson, Membership, Revision
from .studio import json_body


def clean_title(value, fallback):
    title = " ".join(str(value or "").split())[:200]
    return title or fallback


def next_position(queryset):
    return max([0, *queryset.values_list("position", flat=True)]) + 1


def author(request, course):
    return Membership.objects.get(user=request.user, course=course, active=True).user


def copy_revision(source, activity, user):
    revision = Revision.objects.create(activity=activity, number=1, content=source.content,
                                       grading=source.grading, created_by=user)
    for file in source.files.all():
        with file.blob.open("rb") as stream:
            raw = stream.read()
        ActivityFile.objects.create(revision=revision, path=file.path, visibility=file.visibility,
            blob=ContentFile(raw, name=PurePosixPath(file.path).name), sha256=file.sha256)
    activity.published_revision = revision
    activity.save(update_fields=["published_revision"])
    return revision


def reorder_within(queryset, ids):
    """Reassign `queryset`'s existing position values to match the requested order.

    Reusing the exact multiset of positions already held by this subset keeps other rows
    (a different lesson's activities, or lessons outside this one's course view) untouched,
    even though `position` is a single shared ordering column.
    """
    ids = ids if isinstance(ids, list) else []
    all_ids = set(queryset.values_list("pk", flat=True))
    if not ids or set(ids) != all_ids or len(ids) != len(set(ids)):
        return None
    rows = {row.pk: row for row in queryset.filter(pk__in=ids)}
    slots = sorted(row.position for row in rows.values())
    changed = []
    for slot, pk in zip(slots, ids):
        row = rows[pk]
        if row.position != slot:
            row.position = slot
            changed.append(row)
    for row in changed:
        row.save(update_fields=["position"])
    return [rows[pk].pk for pk in ids]


PART_KINDS = {
    "reading": {
        "category": "content",
        "metadata": {"kind": "reading"},
        "content": {"version": 1, "blocks": [{"id": "content", "type": "document",
            "content": [{"type": "text", "text": "Add content in Config."}]}]},
        "grading": {"maximum_points": "0"},
    },
    "video": {
        "category": "content",
        "metadata": {"kind": "video"},
        "content": {"version": 1, "blocks": [{"id": "video", "type": "video", "url": ""}]},
        "grading": {"maximum_points": "0"},
    },
    "coding": {
        "category": "problem_set",
        "metadata": {"kind": "coding"},
        "content": {"version": 1, "blocks": [{"id": "prompt", "type": "coding",
            "prompt": [{"type": "text", "text": "Describe the exercise here, then add files and a grading definition in Config."}]}]},
        "grading": {"maximum_points": "1", "placeholder": True},
    },
    "quiz": {
        "category": "problem_set",
        "metadata": {"kind": "quiz"},
        "content": {"version": 1, "blocks": [{"id": "q1", "type": "multiple_choice",
            "prompt": [{"type": "text", "text": "Question text"}],
            "choices": [{"id": "a", "content": [{"type": "text", "text": "Choice A"}]},
                        {"id": "b", "content": [{"type": "text", "text": "Choice B"}]}]}]},
        "grading": {"maximum_points": "1", "questions": {"q1": {"selection": "one", "correct_choice_ids": ["a"]}}},
    },
}


@require_POST
@json_body
@transaction.atomic
def lessons(request):
    course = staff_course(request)
    return lesson_action(request, course, request.payload)


def lesson_action(request, course, payload):
    action = payload.get("action")
    if action == "create":
        lesson = Lesson.objects.create(course=course,
            title=clean_title(payload.get("title"), "Untitled section"),
            position=next_position(course.lesson_set.filter(deleted_at=None)),
            metadata={"kind": "lesson"})
        return JsonResponse({"ok": True, "id": lesson.pk})
    if action == "reorder":
        # The homepage shows "Course" sections and "Programming quizzes" as two separate, independently
        # reordered lists even though Lesson.position is one shared ordering column across the course, so
        # a reorder request only ever carries one group's ids; scope validation to that same group.
        ids = payload.get("lesson_ids")
        quiz_ids = set(course.lesson_set.filter(deleted_at=None, metadata__kind="programming_quiz").values_list("pk", flat=True))
        is_quiz_group = bool(ids) and set(ids) <= quiz_ids
        group = course.lesson_set.filter(deleted_at=None, pk__in=quiz_ids) if is_quiz_group             else course.lesson_set.filter(deleted_at=None).exclude(pk__in=quiz_ids)
        order = reorder_within(group, ids)
        if order is None: return JsonResponse({"error": "Send every section's id, each exactly once."}, status=400)
        return JsonResponse({"ok": True, "order": order})
    lesson = get_object_or_404(Lesson, pk=payload.get("lesson_id"), course=course, deleted_at=None)
    if action == "rename":
        value = payload.get("title")
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
            return JsonResponse({"error": "Enter a title between 1 and 200 characters."}, status=400)
        lesson.title = value.strip(); lesson.save(update_fields=["title"])
        return JsonResponse({"ok": True, "id": lesson.pk})
    if action == "delete":
        from django.utils import timezone
        lesson.deleted_at = timezone.now(); lesson.save(update_fields=["deleted_at"])
        return JsonResponse({"ok": True})
    if action == "copy":
        duplicate = Lesson.objects.create(course=course,
            title=clean_title(payload.get("title"), f"Copy of {lesson.title}"),
            position=next_position(course.lesson_set.filter(deleted_at=None)),
            visibility=lesson.visibility, metadata={**lesson.metadata})
        user = author(request, course)
        part_ids = {}
        for source_activity in lesson.activity_set.filter(deleted_at=None).order_by("position"):
            copied = Activity.objects.create(lesson=duplicate, title=source_activity.title,
                position=source_activity.position, metadata={**source_activity.metadata})
            source_revision = source_activity.published_revision or source_activity.revisions.order_by("-number").first()
            if source_revision: copy_revision(source_revision, copied, user)
            part_ids[str(source_activity.pk)] = copied.pk
        return JsonResponse({"ok": True, "id": duplicate.pk, "part_ids": part_ids})
    return JsonResponse({"error": "Unknown outline action."}, status=400)


@require_POST
@json_body
@transaction.atomic
def activities(request):
    course = staff_course(request)
    return activity_action(request, course, request.payload)


def activity_action(request, course, payload):
    action = payload.get("action")
    lesson = get_object_or_404(Lesson, pk=payload.get("lesson_id"), course=course, deleted_at=None)
    user = author(request, course)
    if action == "create":
        template = PART_KINDS.get(payload.get("kind"), PART_KINDS["reading"])
        activity = Activity.objects.create(lesson=lesson,
            title=clean_title(payload.get("title"), "Untitled part"),
            position=next_position(lesson.activity_set.filter(deleted_at=None)),
            metadata={**template["metadata"], "category": template["category"], "group": "New section"})
        revision = Revision.objects.create(activity=activity, number=1, created_by=user,
            content=template["content"], grading=template["grading"])
        activity.published_revision = revision; activity.save(update_fields=["published_revision"])
        return JsonResponse({"ok": True, "id": activity.pk})
    if action == "reorder":
        order = reorder_within(lesson.activity_set.filter(deleted_at=None), payload.get("activity_ids"))
        if order is None: return JsonResponse({"error": "Send every part's id, each exactly once."}, status=400)
        return JsonResponse({"ok": True, "order": order})
    source = get_object_or_404(Activity, pk=payload.get("activity_id"), lesson__course=course, deleted_at=None)
    if action == "rename":
        value = payload.get("title")
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
            return JsonResponse({"error": "Enter a title between 1 and 200 characters."}, status=400)
        source.title = value.strip(); source.save(update_fields=["title"])
        return JsonResponse({"ok": True, "id": source.pk})
    if action == "delete":
        from django.utils import timezone
        source.deleted_at = timezone.now(); source.save(update_fields=["deleted_at"])
        return JsonResponse({"ok": True})
    if action == "copy":
        copied = Activity.objects.create(lesson=lesson,
            title=clean_title(payload.get("title"), f"Copy of {source.title}"),
            position=next_position(lesson.activity_set.filter(deleted_at=None)),
            metadata={**source.metadata})
        source_revision = source.published_revision or source.revisions.order_by("-number").first()
        if source_revision: copy_revision(source_revision, copied, user)
        return JsonResponse({"ok": True, "id": copied.pk})
    return JsonResponse({"error": "Unknown outline action."}, status=400)


def structure_state(course):
    """A staff-only outline plus a content-sensitive optimistic concurrency token."""
    lessons = list(course.lesson_set.filter(deleted_at=None).order_by("position", "pk"))
    parts = list(Activity.objects.filter(lesson__in=lessons, deleted_at=None)
        .annotate(latest_revision=Max("revisions__pk")).order_by("position", "pk"))
    by_lesson = {lesson.pk: [] for lesson in lessons}
    fingerprint = []
    for part in parts:
        by_lesson[part.lesson_id].append({"id": part.pk, "title": part.title,
            "metadata": part.metadata, "status": "", "earned_points": "0", "maximum_points": "0"})
        fingerprint.append([part.pk, part.lesson_id, part.title, part.position, part.metadata,
                            part.published_revision_id, part.latest_revision])
    rows = [{"id": lesson.pk, "title": lesson.title, "metadata": lesson.metadata,
             "activities": by_lesson[lesson.pk]} for lesson in lessons]
    version = hashlib.sha256(json.dumps([
        [[l.pk, l.title, l.position, l.visibility, l.metadata] for l in lessons], fingerprint
    ], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"version": version, "lessons": rows}


@require_GET
def draft(request):
    return JsonResponse(structure_state(staff_course(request)))


@require_POST
@json_body
@transaction.atomic
def save_draft(request):
    course = staff_course(request)
    # Serialize structure saves and lock existing rows against concurrent authoring.
    type(course).objects.select_for_update().get(pk=course.pk)
    list(course.lesson_set.select_for_update().order_by("pk").values_list("pk", flat=True))
    list(Activity.objects.select_for_update().filter(lesson__course=course).order_by("pk").values_list("pk", flat=True))
    if request.payload.get("base_version") != structure_state(course)["version"]:
        return JsonResponse({"error": "The course changed while you were editing. Your draft is still here. Discard it and reload the structure before trying again."}, status=409)
    operations = request.payload.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 500:
        return JsonResponse({"error": "Save between 1 and 500 structure changes at a time."}, status=400)
    ids = {}
    def resolve(value):
        if type(value) is not int: raise ValueError("Structure IDs must be integers.")
        if value < 0:
            if value not in ids: raise ValueError("Unknown draft item.")
            return ids[value]
        return value
    def remember(client_id, actual_id):
        if type(client_id) is not int or client_id >= 0 or client_id in ids:
            raise ValueError("Draft item IDs must be unique negative integers.")
        ids[client_id] = actual_id
    try:
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("entity") not in {"lesson", "part"}:
                raise ValueError("Unknown structure operation.")
            payload = dict(operation)
            entity = payload.pop("entity")
            client_id = payload.pop("client_id", None)
            children = payload.pop("client_part_ids", {})
            if payload.get("action") not in {"create", "copy", "delete", "rename", "reorder"}:
                raise ValueError("Unknown structure action.")
            for field in ("lesson_id", "activity_id"):
                if field in payload: payload[field] = resolve(payload[field])
            for field in ("lesson_ids", "activity_ids"):
                if field in payload:
                    if not isinstance(payload[field], list): raise ValueError("Send a list of item IDs.")
                    payload[field] = [resolve(value) for value in payload[field]]
            result = (lesson_action if entity == "lesson" else activity_action)(request, course, payload)
            if result.status_code >= 400:
                transaction.set_rollback(True)
                return result
            result = json.loads(result.content)
            if payload["action"] in {"create", "copy"}: remember(client_id, result["id"])
            if children:
                if entity != "lesson" or payload["action"] != "copy" or not isinstance(children, dict):
                    raise ValueError("Unexpected copied parts.")
                for old_id, temp_id in children.items():
                    new_id = result.get("part_ids", {}).get(str(resolve(int(old_id))))
                    if new_id is None: raise ValueError("Copied part changed; reload the structure.")
                    remember(temp_id, new_id)
    except (ValueError, TypeError, KeyError) as exc:
        transaction.set_rollback(True)
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **structure_state(course)})
