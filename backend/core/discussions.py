"""Course-scoped discussion board with staff controls and student projections."""
import csv
from io import StringIO
from pathlib import Path
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .course_context import current_membership
from .models import (DiscussionAnswer, DiscussionAttachment, DiscussionBoardSettings, DiscussionDraft, DiscussionFolder, DiscussionPostRevision,
    DiscussionPollOption, DiscussionPollVote, DiscussionReply, DiscussionReplyLike,
    DiscussionThread, DiscussionThreadState, Membership)
from .studio import json_body

SETTING_FIELDS = ("allow_student_posts", "allow_student_notes", "allow_student_polls",
    "allow_anonymous", "allow_anonymous_to_staff", "allow_private", "allow_student_answers", "require_folder", "reading_list_enabled", "require_reading_before_posting")
ANON = {"none", "classmates", "everyone"}
EDITOR_MODES = {"formatted", "plain", "markdown"}


def current_member(request):
    return current_membership(request)


def is_staff(request, member):
    return member.role != "student" and request.session.get("student_view_course") != member.course_id


def require_staff(request):
    member = current_member(request)
    if not is_staff(request, member): raise PermissionDenied
    return member


def board_settings(course):
    settings, _ = DiscussionBoardSettings.objects.get_or_create(course=course)
    return settings


def reading_counts(member):
    read_state = DiscussionThreadState.objects.filter(thread=OuterRef("pk"), membership=member,
        read_at__gte=OuterRef("updated_at"))
    unread = DiscussionThread.objects.filter(course=member.course, deleted_at=None, visibility="public",
        reading_list=True).annotate(read_by_member=Exists(read_state)).filter(read_by_member=False)
    return {"unread": unread.count(), "required": unread.filter(required_reading=True).count()}


def author_name(member):
    return (member.user.get_full_name() or member.user.username)[:150] if member else "Former member"


def display_author(label, author, anonymous, viewer, staff):
    if author and author.pk == viewer.pk: return label or author_name(author)
    if anonymous == "everyone" or anonymous == "classmates" and not staff: return "Anonymous"
    return label or author_name(author)


def visible_threads(member, staff):
    query = DiscussionThread.objects.filter(course=member.course, deleted_at=None)
    return query if staff else query.filter(Q(visibility="public") | Q(author=member))


def visible_thread(request, pk, member):
    return get_object_or_404(visible_threads(member, is_staff(request, member))
        .select_related("author__user").prefetch_related("folders", "answers"), pk=pk)


def valid_text(value, maximum):
    return isinstance(value, str) and 0 < len(value.strip()) <= maximum


def nonnegative(value):
    try: result = int(value)
    except (TypeError, ValueError): return None
    return result if 0 <= result <= 100000 else None


def thread_data(thread, member, staff, state=None):
    state = state or DiscussionThreadState(thread=thread, membership=member)
    answers = {answer.kind: answer for answer in thread.answers.all()}
    visible_name = display_author(thread.author_label, thread.author, thread.anonymous, member, staff)
    return {"id": thread.pk, "title": thread.title, "body": thread.body, "editor_mode": thread.editor_mode, "kind": thread.kind,
        "visibility": thread.visibility, "anonymous": thread.anonymous,
        "author": visible_name,
        "mine": thread.author_id == member.pk,
        "author_is_staff": bool(visible_name != "Anonymous" and thread.author and thread.author.role != "student"),
        "created_at": thread.created_at.isoformat(), "updated_at": thread.updated_at.isoformat(),
        "folders": [{"id": row.pk, "name": row.name} for row in thread.folders.all()],
        "pinned": thread.pinned, "reading_list": thread.reading_list, "required_reading": thread.required_reading, "locked": thread.locked,
        "endorsed": thread.endorsed, "history_hidden": thread.history_hidden,
        "history_count": getattr(thread, "history_count", 0),
        "reply_count": getattr(thread, "reply_count", 0),
        "unresolved_count": getattr(thread, "unresolved_count", 0),
        "view_count": getattr(thread, "view_count", 0), "like_count": getattr(thread, "like_count", 0),
        "has_student_answer": "student" in answers, "has_instructor_answer": "instructor" in answers,
        "student_answer_endorsed": bool(answers.get("student") and answers["student"].endorsed),
        "read": bool(state.read_at and state.read_at >= thread.updated_at),
        "bookmarked": state.bookmarked, "following": state.following,
        "archived": state.archived, "liked": state.liked}


def annotated(query):
    return query.select_related("author__user").prefetch_related("folders", "answers").annotate(
        reply_count=Count("replies", filter=Q(replies__deleted_at=None, replies__parent__isnull=True), distinct=True),
        unresolved_count=Count("replies", filter=Q(replies__deleted_at=None, replies__parent__isnull=True, replies__resolved=False), distinct=True),
        view_count=Count("member_states", filter=Q(member_states__read_at__isnull=False), distinct=True),
        like_count=Count("member_states", filter=Q(member_states__liked=True), distinct=True),
        history_count=Count("revisions", distinct=True))


@require_GET
def meta(request):
    member = current_member(request)
    settings = board_settings(member.course)
    return JsonResponse({"staff": is_staff(request, member), "viewer_name": author_name(member), "reading": reading_counts(member),
        "settings": {field: getattr(settings, field) for field in SETTING_FIELDS},
        "folders": [{"id": row.pk, "name": row.name, "position": row.position}
                    for row in member.course.discussion_folders.all()]})


@require_GET
def get_draft(request):
    member = current_member(request)
    draft = DiscussionDraft.objects.filter(course=member.course, author=member).first()
    if draft is None: return JsonResponse({"draft": None})
    return JsonResponse({"draft": {"title": draft.title, "body": draft.body, "editor_mode": draft.editor_mode, "kind": draft.kind,
        "visibility": draft.visibility, "anonymous": draft.anonymous, "folder_ids": draft.folder_ids,
        "options": draft.options, "updated_at": draft.updated_at.isoformat()}})


@require_POST
@json_body
def save_draft(request):
    member = current_member(request); payload = request.payload
    if set(payload) != {"title", "body", "editor_mode", "kind", "visibility", "anonymous", "folder_ids", "options"} or \
        not isinstance(payload["title"], str) or len(payload["title"]) > 160 or \
        not isinstance(payload["body"], str) or len(payload["body"]) > 10000 or \
        not isinstance(payload["editor_mode"], str) or payload["editor_mode"] not in EDITOR_MODES or \
        not isinstance(payload["kind"], str) or payload["kind"] not in {"question", "note", "poll"} or \
        not isinstance(payload["visibility"], str) or payload["visibility"] not in {"public", "private"} or \
        not isinstance(payload["anonymous"], str) or payload["anonymous"] not in ANON or \
        not isinstance(payload["options"], list) or len(payload["options"]) > 8 or \
        any(not isinstance(option, str) or len(option) > 240 for option in payload["options"]):
        return JsonResponse({"error": "The draft has invalid fields."}, status=400)
    ids = payload["folder_ids"]
    if not isinstance(ids, list) or any(type(pk) is not int for pk in ids) or len(ids) > 5 or len(set(ids)) != len(ids) or \
        DiscussionFolder.objects.filter(course=member.course, pk__in=ids).count() != len(ids):
        return JsonResponse({"error": "Choose valid folders for the draft."}, status=400)
    draft, _ = DiscussionDraft.objects.update_or_create(course=member.course, author=member,
        defaults={field: payload[field] for field in payload})
    return JsonResponse({"updated_at": draft.updated_at.isoformat()})


@require_POST
@json_body
def discard_draft(request):
    member = current_member(request)
    DiscussionDraft.objects.filter(course=member.course, author=member).delete()
    return JsonResponse({"ok": True})


@require_POST
@json_body
def save_settings(request):
    member = require_staff(request)
    if not request.payload or set(request.payload) - set(SETTING_FIELDS) or any(type(value) is not bool for value in request.payload.values()):
        return JsonResponse({"error": "Send board settings as true or false values."}, status=400)
    settings = board_settings(member.course)
    for field, value in request.payload.items(): setattr(settings, field, value)
    settings.save(update_fields=list(request.payload))
    return JsonResponse({"settings": {field: getattr(settings, field) for field in SETTING_FIELDS}})


@require_POST
@json_body
@transaction.atomic
def folders(request):
    member = require_staff(request)
    query = DiscussionFolder.objects.filter(course=member.course)
    action = request.payload.get("action")
    if action in {"create", "rename"}:
        name = request.payload.get("name")
        if not valid_text(name, 60): return JsonResponse({"error": "Enter a folder name of up to 60 characters."}, status=400)
        if action == "create":
            if query.filter(name=name.strip()).exists(): return JsonResponse({"error": "That folder already exists."}, status=400)
            query.create(course=member.course, name=name.strip(), position=query.count())
        else:
            row = get_object_or_404(query, pk=request.payload.get("id"))
            if query.filter(name=name.strip()).exclude(pk=row.pk).exists(): return JsonResponse({"error": "That folder already exists."}, status=400)
            row.name = name.strip(); row.save(update_fields=["name"])
    elif action == "delete": get_object_or_404(query, pk=request.payload.get("id")).delete()
    elif action == "reorder":
        ids = request.payload.get("ids")
        if not isinstance(ids, list) or any(type(pk) is not int for pk in ids) or len(ids) != query.count() or set(ids) != set(query.values_list("pk", flat=True)):
            return JsonResponse({"error": "Send every folder ID once."}, status=400)
        for position, pk in enumerate(ids): query.filter(pk=pk).update(position=position)
    else: return JsonResponse({"error": "Choose a folder action."}, status=400)
    return JsonResponse({"folders": [{"id": row.pk, "name": row.name, "position": row.position} for row in query]})


@require_GET
def list_threads(request):
    member = current_member(request); staff = is_staff(request, member)
    offset = nonnegative(request.GET.get("offset", "0"))
    if offset is None: return JsonResponse({"error": "Invalid discussion offset."}, status=400)
    query = visible_threads(member, staff)
    search = request.GET.get("q", "").strip()[:100]
    if search: query = query.filter(Q(title__icontains=search) | Q(body__icontains=search) | Q(folders__name__icontains=search)).distinct()
    folder = request.GET.get("folder")
    if folder:
        folder_id = nonnegative(folder)
        if folder_id is None: return JsonResponse({"error": "Invalid folder."}, status=400)
        query = query.filter(folders__id=folder_id)
    kind = request.GET.get("kind")
    if kind in {"question", "note", "poll"}: query = query.filter(kind=kind)
    state_query = DiscussionThreadState.objects.filter(thread=OuterRef("pk"), membership=member)
    query = query.annotate(is_bookmarked=Exists(state_query.filter(bookmarked=True)),
        is_following=Exists(state_query.filter(following=True)),
        is_archived=Exists(state_query.filter(archived=True)),
        is_read=Exists(state_query.filter(read_at__gte=OuterRef("updated_at"))),
        has_answer=Exists(DiscussionAnswer.objects.filter(thread=OuterRef("pk"))),
        has_open_followup=Exists(DiscussionReply.objects.filter(thread=OuterRef("pk"), parent=None, resolved=False, deleted_at=None)))
    choice = request.GET.get("filter", "all")
    if choice == "unread": query = query.filter(is_read=False)
    elif choice == "unresolved": query = query.filter(kind="question").filter(Q(has_answer=False) | Q(has_open_followup=True))
    elif choice == "following": query = query.filter(is_following=True)
    elif choice == "bookmarked": query = query.filter(is_bookmarked=True)
    elif choice == "reading": query = query.filter(reading_list=True)
    elif choice == "mine": query = query.filter(author=member)
    elif choice == "instructor": query = query.exclude(author__role="student")
    elif choice == "archived": query = query.filter(is_archived=True)
    elif choice != "all": return JsonResponse({"error": "Invalid discussion filter."}, status=400)
    if choice != "archived": query = query.filter(is_archived=False)
    sort = request.GET.get("sort", "recent")
    if sort == "newest": query = query.order_by("-created_at", "-pk")
    elif sort == "oldest": query = query.order_by("created_at", "pk")
    elif sort == "recent": query = query.order_by("-pinned", "-reading_list", "-updated_at", "-pk")
    else: return JsonResponse({"error": "Invalid sort order."}, status=400)
    rows = list(annotated(query)[offset:offset + 31])
    states = {row.thread_id: row for row in DiscussionThreadState.objects.filter(membership=member, thread_id__in=[thread.pk for thread in rows])}
    return JsonResponse({"threads": [thread_data(row, member, staff, states.get(row.pk)) for row in rows[:30]], "has_more": len(rows) > 30})


def selected_folders(payload, member, required):
    ids = payload.get("folder_ids", [])
    if not isinstance(ids, list) or any(type(pk) is not int for pk in ids) or len(ids) != len(set(ids)) or len(ids) > 5: return None
    rows = list(DiscussionFolder.objects.filter(course=member.course, pk__in=ids))
    return rows if len(rows) == len(ids) and (rows or not required) else None


@require_POST
@json_body
@transaction.atomic
def create_thread(request):
    member = current_member(request); staff = is_staff(request, member); settings = board_settings(member.course)
    payload = request.payload
    if set(payload) - {"title", "body", "editor_mode", "kind", "visibility", "anonymous", "folder_ids", "options"} or not valid_text(payload.get("title"), 160) or not valid_text(payload.get("body"), 10000):
        return JsonResponse({"error": "Add a title (up to 160 characters) and message (up to 10,000 characters)."}, status=400)
    kind, visibility, anonymous = payload.get("kind", "question"), payload.get("visibility", "public"), payload.get("anonymous", "none")
    editor_mode = payload.get("editor_mode", "formatted")
    if not isinstance(kind, str) or kind not in {"question", "note", "poll"} or not isinstance(visibility, str) or visibility not in {"public", "private"} or not isinstance(anonymous, str) or anonymous not in ANON or not isinstance(editor_mode, str) or editor_mode not in EDITOR_MODES:
        return JsonResponse({"error": "Choose a valid post type, visibility, and name setting."}, status=400)
    if not staff and (not settings.allow_student_posts or kind == "note" and not settings.allow_student_notes
        or kind == "poll" and not settings.allow_student_polls or visibility == "private" and not settings.allow_private
        or anonymous != "none" and not settings.allow_anonymous
        or anonymous == "everyone" and not settings.allow_anonymous_to_staff): raise PermissionDenied
    if not staff and settings.reading_list_enabled and settings.require_reading_before_posting and reading_counts(member)["required"]:
        return JsonResponse({"error": "Read the required items in your reading list before posting."}, status=403)
    folder_rows = selected_folders(payload, member, settings.require_folder)
    if folder_rows is None: return JsonResponse({"error": "Choose a valid course folder."}, status=400)
    options = payload.get("options", [])
    if kind == "poll":
        if not isinstance(options, list) or not 2 <= len(options) <= 8 or any(not valid_text(label, 240) for label in options):
            return JsonResponse({"error": "Add 2 to 8 poll choices, each up to 240 characters."}, status=400)
    elif options: return JsonResponse({"error": "Poll choices require a poll post."}, status=400)
    thread = DiscussionThread.objects.create(course=member.course, author=member,
        author_label=author_name(member), title=payload["title"].strip(), body=payload["body"].strip(), editor_mode=editor_mode,
        kind=kind, visibility=visibility, anonymous=anonymous)
    thread.folders.set(folder_rows)
    DiscussionPostRevision.objects.create(thread=thread, version=1, title=thread.title, body=thread.body, editor_mode=thread.editor_mode,
        editor_label=author_name(member))
    for position, label in enumerate(options): DiscussionPollOption.objects.create(thread=thread, label=label.strip(), position=position)
    DiscussionDraft.objects.filter(course=member.course, author=member).delete()
    thread.reply_count = thread.unresolved_count = thread.view_count = thread.like_count = 0
    thread.history_count = 1
    return JsonResponse({"thread": thread_data(thread, member, staff)}, status=201)


def reply_data(reply, member, staff):
    visible_name = display_author(reply.author_label, reply.author, reply.anonymous, member, staff)
    return {"id": reply.pk, "parent_id": reply.parent_id, "body": reply.body,
        "author": visible_name,
        "author_is_staff": bool(visible_name != "Anonymous" and reply.author and reply.author.role != "student"),
        "mine": reply.author_id == member.pk, "resolved": reply.resolved,
        "created_at": reply.created_at.isoformat(), "like_count": getattr(reply, "like_count", 0),
        "liked": bool(getattr(reply, "liked", False))}


@require_GET
def read_thread(request, pk):
    member = current_member(request); staff = is_staff(request, member); thread = visible_thread(request, pk, member)
    offset = nonnegative(request.GET.get("offset", "0"))
    if offset is None: return JsonResponse({"error": "Invalid reply offset."}, status=400)
    state, _ = DiscussionThreadState.objects.get_or_create(thread=thread, membership=member)
    if offset == 0: state.read_at = timezone.now(); state.save(update_fields=["read_at"])
    thread.reply_count = thread.replies.filter(parent=None, deleted_at=None).count()
    thread.unresolved_count = thread.replies.filter(parent=None, resolved=False, deleted_at=None).count()
    thread.view_count = thread.member_states.filter(read_at__isnull=False).count()
    thread.like_count = thread.member_states.filter(liked=True).count()
    thread.history_count = thread.revisions.count()
    replies = list(thread.replies.filter(deleted_at=None).select_related("author__user")
        .annotate(like_count=Count("likes"), liked=Exists(DiscussionReplyLike.objects.filter(reply=OuterRef("pk"), membership=member)))
        .order_by("created_at", "pk")[offset:offset + 51])
    answers = {row.kind: {"body": row.body, "author": row.last_editor_label,
        "endorsed": row.endorsed, "updated_at": row.updated_at.isoformat()} for row in thread.answers.all()}
    options = list(thread.poll_options.order_by("position", "pk")
        .annotate(votes_count=Count("votes")).values("id", "label", "votes_count")) if thread.kind == "poll" else []
    my_vote = thread.poll_votes.filter(membership=member).values_list("option_id", flat=True).first() if thread.kind == "poll" else None
    return JsonResponse({"thread": thread_data(thread, member, staff, state), "answers": answers,
        "replies": [reply_data(row, member, staff) for row in replies[:50]], "has_more_replies": len(replies) > 50,
        "poll_options": options, "my_vote": my_vote,
        "attachments": [{"id": row.pk, "name": row.name, "size": row.size, "mine": row.uploader_id == member.pk}
            for row in thread.attachments.filter(deleted_at=None).order_by("created_at", "pk")]})


@require_POST
def upload_attachment(request, pk):
    member = current_member(request); staff = is_staff(request, member)
    thread = visible_thread(request, pk, member)
    if thread.locked and not staff: raise PermissionDenied
    file = request.FILES.get("file")
    if not file or file.size <= 0 or file.size > 2_000_000:
        return JsonResponse({"error": "Choose a file under 2 MB."}, status=400)
    name = Path(file.name.replace("\\", "/")).name[:120]
    if Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".py", ".ipynb"}:
        return JsonResponse({"error": "Use an image, PDF, text, Python, or notebook file."}, status=400)
    item = DiscussionAttachment.objects.create(thread=thread, uploader=member, name=name, blob=file, size=file.size)
    return JsonResponse({"attachment": {"id": item.pk, "name": item.name, "size": item.size, "mine": True}}, status=201)


@require_GET
def download_attachment(request, pk):
    member = current_member(request)
    item = get_object_or_404(DiscussionAttachment.objects.select_related("thread"), pk=pk, deleted_at=None,
        thread__course=member.course, thread__deleted_at=None)
    visible_thread(request, item.thread_id, member)
    return FileResponse(item.blob.open("rb"), as_attachment=True, filename=item.name, content_type="application/octet-stream")


@require_POST
@json_body
def remove_attachment(request, pk):
    member = current_member(request)
    item = get_object_or_404(DiscussionAttachment, pk=pk, deleted_at=None,
        thread__course=member.course, thread__deleted_at=None)
    visible_thread(request, item.thread_id, member)
    if not is_staff(request, member) and item.uploader_id != member.pk: raise PermissionDenied
    item.deleted_at = timezone.now(); item.save(update_fields=["deleted_at"])
    return JsonResponse({"ok": True})


@require_POST
@json_body
def create_reply(request, pk):
    member = current_member(request); staff = is_staff(request, member); thread = visible_thread(request, pk, member)
    if thread.locked and not staff: raise PermissionDenied
    payload = request.payload; anonymous = payload.get("anonymous", "none")
    if set(payload) - {"body", "parent_id", "anonymous"} or not valid_text(payload.get("body"), 10000) or anonymous not in ANON:
        return JsonResponse({"error": "Write a followup of up to 10,000 characters."}, status=400)
    if anonymous != "none" and not staff:
        settings = board_settings(member.course)
        if not settings.allow_anonymous or anonymous == "everyone" and not settings.allow_anonymous_to_staff: raise PermissionDenied
    parent = None
    if payload.get("parent_id") is not None:
        parent = get_object_or_404(DiscussionReply, pk=payload["parent_id"], thread=thread, parent=None, deleted_at=None)
    reply = DiscussionReply.objects.create(thread=thread, parent=parent, author=member,
        author_label=author_name(member), body=payload["body"].strip(), anonymous=anonymous)
    thread.save(update_fields=["updated_at"]); reply.like_count = 0
    return JsonResponse({"reply": reply_data(reply, member, staff)}, status=201)


@require_POST
@json_body
def save_answer(request, pk):
    member = current_member(request); staff = is_staff(request, member); thread = visible_thread(request, pk, member)
    kind, body = request.payload.get("kind"), request.payload.get("body")
    if set(request.payload) != {"kind", "body"} or kind not in {"student", "instructor"} or not valid_text(body, 10000):
        return JsonResponse({"error": "Choose an answer area and write up to 10,000 characters."}, status=400)
    if thread.kind != "question" or thread.locked and not staff or kind == "instructor" and not staff or kind == "student" and not staff and not board_settings(member.course).allow_student_answers: raise PermissionDenied
    answer, _ = DiscussionAnswer.objects.update_or_create(thread=thread, kind=kind,
        defaults={"body": body.strip(), "last_editor": member, "last_editor_label": author_name(member)})
    thread.save(update_fields=["updated_at"])
    return JsonResponse({"answer": {"body": answer.body, "author": answer.last_editor_label,
        "endorsed": answer.endorsed, "updated_at": answer.updated_at.isoformat()}})


@require_POST
@json_body
def thread_action(request, pk):
    member = current_member(request); staff = is_staff(request, member); thread = visible_thread(request, pk, member)
    action, value = request.payload.get("action"), request.payload.get("value")
    if set(request.payload) != {"action", "value"} or type(value) is not bool:
        return JsonResponse({"error": "Choose an action and true or false."}, status=400)
    staff_fields = {"pin": "pinned", "reading_list": "reading_list", "required_reading": "required_reading", "lock": "locked", "endorse": "endorsed", "hide_history": "history_hidden"}
    personal_fields = {"bookmark": "bookmarked", "follow": "following", "archive": "archived", "like": "liked"}
    if action in staff_fields:
        if not staff or action in {"reading_list", "required_reading"} and not board_settings(member.course).reading_list_enabled: raise PermissionDenied
        if action == "required_reading" and value and thread.visibility != "public": raise PermissionDenied
        field = staff_fields[action]; setattr(thread, field, value)
        updated_fields = [field]
        if action == "required_reading" and value: thread.reading_list = True; updated_fields.append("reading_list")
        if action == "reading_list" and not value: thread.required_reading = False; updated_fields.append("required_reading")
        if action in {"reading_list", "required_reading"}: updated_fields.append("updated_at")
        thread.save(update_fields=updated_fields)
    elif action in personal_fields or action == "read":
        if action == "read" and value: return JsonResponse({"error": "Open the post to mark it read."}, status=400)
        state, _ = DiscussionThreadState.objects.get_or_create(thread=thread, membership=member)
        field = "read_at" if action == "read" else personal_fields[action]
        setattr(state, field, (timezone.now() if value else None) if action == "read" else value)
        state.save(update_fields=[field])
    else: return JsonResponse({"error": "Unknown discussion action."}, status=400)
    return JsonResponse({"ok": True})


@require_POST
@json_body
@transaction.atomic
def edit_thread(request, pk):
    member = current_member(request); staff = is_staff(request, member); thread = visible_thread(request, pk, member)
    if not staff and (thread.author_id != member.pk or thread.locked): raise PermissionDenied
    payload = request.payload
    if set(payload) - {"title", "body", "editor_mode", "folder_ids", "visibility", "anonymous"} or not valid_text(payload.get("title"), 160) or not valid_text(payload.get("body"), 10000):
        return JsonResponse({"error": "Enter a title and message."}, status=400)
    visibility = payload.get("visibility", thread.visibility)
    anonymous = payload.get("anonymous", thread.anonymous)
    editor_mode = payload.get("editor_mode", thread.editor_mode)
    if not isinstance(visibility, str) or visibility not in {"public", "private"} or not isinstance(anonymous, str) or anonymous not in ANON or not isinstance(editor_mode, str) or editor_mode not in EDITOR_MODES:
        return JsonResponse({"error": "Choose valid visibility and name settings."}, status=400)
    settings = board_settings(member.course)
    if not staff and (visibility == "private" and not settings.allow_private or
        anonymous != "none" and not settings.allow_anonymous or
        anonymous == "everyone" and not settings.allow_anonymous_to_staff): raise PermissionDenied
    rows = selected_folders(payload, member, board_settings(member.course).require_folder)
    if rows is None: return JsonResponse({"error": "Choose a valid course folder."}, status=400)
    thread = DiscussionThread.objects.select_for_update().get(pk=thread.pk)
    thread.title, thread.body = payload["title"].strip(), payload["body"].strip()
    thread.visibility, thread.anonymous, thread.editor_mode = visibility, anonymous, editor_mode
    updated_fields = ["title", "body", "visibility", "anonymous", "editor_mode", "updated_at"]
    if visibility == "private" and thread.required_reading:
        thread.required_reading = False; updated_fields.append("required_reading")
    thread.save(update_fields=updated_fields); thread.folders.set(rows)
    version = (thread.revisions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    DiscussionPostRevision.objects.create(thread=thread, version=version, title=thread.title,
        body=thread.body, editor_mode=thread.editor_mode, editor_label=author_name(member))
    return JsonResponse({"ok": True})


@require_GET
def history(request, pk):
    member = current_member(request); thread = visible_thread(request, pk, member)
    if thread.history_hidden and not is_staff(request, member): raise PermissionDenied
    revisions = list(thread.revisions.order_by("version").values("version", "title", "body", "editor_mode", "editor_label", "created_at"))
    if not revisions:
        revisions = [{"version": 1, "title": thread.title, "body": thread.body, "editor_mode": thread.editor_mode,
            "editor_label": thread.author_label, "created_at": thread.created_at}]
    for row in revisions:
        row["created_at"] = row["created_at"].isoformat()
        if thread.author_id != member.pk and (thread.anonymous == "everyone" or
            thread.anonymous == "classmates" and not is_staff(request, member)):
            row["editor_label"] = "Anonymous"
    return JsonResponse({"revisions": revisions})


@require_POST
@json_body
def delete_thread(request, pk):
    member = require_staff(request); thread = visible_thread(request, pk, member)
    thread.deleted_at = timezone.now(); thread.save(update_fields=["deleted_at"])
    return JsonResponse({"ok": True})


@require_POST
@json_body
def reply_action(request, pk):
    member = current_member(request); staff = is_staff(request, member)
    reply = get_object_or_404(DiscussionReply.objects.select_related("thread"), pk=pk,
        thread__course=member.course, thread__deleted_at=None, deleted_at=None)
    visible_thread(request, reply.thread_id, member)
    action, value = request.payload.get("action"), request.payload.get("value")
    if set(request.payload) != {"action", "value"} or type(value) is not bool:
        return JsonResponse({"error": "Choose an action and true or false."}, status=400)
    if action == "like":
        if value: DiscussionReplyLike.objects.get_or_create(reply=reply, membership=member)
        else: DiscussionReplyLike.objects.filter(reply=reply, membership=member).delete()
    elif action == "resolve":
        if reply.parent_id or not (staff or reply.author_id == member.pk): raise PermissionDenied
        reply.resolved = value; reply.save(update_fields=["resolved"])
    elif action == "delete":
        if not (staff or reply.author_id == member.pk): raise PermissionDenied
        if value: reply.deleted_at = timezone.now(); reply.save(update_fields=["deleted_at"])
    else: return JsonResponse({"error": "Unknown followup action."}, status=400)
    return JsonResponse({"ok": True})


@require_POST
@json_body
def endorse_answer(request, pk):
    member = require_staff(request); thread = visible_thread(request, pk, member)
    if set(request.payload) != {"value"} or type(request.payload["value"]) is not bool:
        return JsonResponse({"error": "Send true or false."}, status=400)
    answer = get_object_or_404(DiscussionAnswer, thread=thread, kind="student")
    answer.endorsed = request.payload["value"]; answer.save(update_fields=["endorsed"])
    return JsonResponse({"endorsed": answer.endorsed})


@require_POST
@json_body
def vote(request, pk):
    member = current_member(request); thread = visible_thread(request, pk, member)
    if thread.kind != "poll" or thread.locked and not is_staff(request, member): raise PermissionDenied
    if set(request.payload) != {"option_id"}: return JsonResponse({"error": "Choose one poll option."}, status=400)
    option = get_object_or_404(DiscussionPollOption, pk=request.payload["option_id"], thread=thread)
    DiscussionPollVote.objects.update_or_create(thread=thread, membership=member, defaults={"option": option})
    return JsonResponse({"ok": True})


@require_GET
def statistics(request):
    member = current_member(request); staff = is_staff(request, member)
    threads = visible_threads(member, staff)
    replies = DiscussionReply.objects.filter(thread__course=member.course, deleted_at=None, thread__deleted_at=None)
    answers = DiscussionAnswer.objects.filter(thread__course=member.course, thread__deleted_at=None)
    if not staff:
        threads = threads.filter(author=member); replies = replies.filter(author=member); answers = answers.filter(last_editor=member)
    result = {"posts": threads.count(), "questions": threads.filter(kind="question").count(),
        "notes": threads.filter(kind="note").count(), "polls": threads.filter(kind="poll").count(),
        "followups": replies.count(), "answers": answers.count(),
        "views": DiscussionThreadState.objects.filter(thread__course=member.course, read_at__isnull=False,
            **({} if staff else {"membership": member})).count()}
    if staff:
        result["unresolved"] = threads.filter(kind="question").exclude(answers__isnull=False).count()
        result["contributors"] = list(Membership.objects.filter(course=member.course, active=True)
            .annotate(posts=Count("discussionthread", filter=Q(discussionthread__deleted_at=None) & ~Q(discussionthread__anonymous="everyone"), distinct=True),
                      followups=Count("discussionreply", filter=Q(discussionreply__deleted_at=None) & ~Q(discussionreply__anonymous="everyone"), distinct=True))
            .select_related("user").order_by("-posts", "-followups")[:20]
            .values("user__first_name", "user__last_name", "user__username", "role", "posts", "followups"))
    return JsonResponse(result)


@require_GET
def statistics_export(request):
    member = require_staff(request)
    members = Membership.objects.filter(course=member.course, active=True).select_related("user")
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Member", "Role", "Posts", "Followups", "Answers", "Post views"])
    for row in members:
        name = author_name(row)
        if name.startswith(("=", "+", "-", "@")): name = "'" + name
        writer.writerow([name, row.role,
            DiscussionThread.objects.filter(course=member.course, author=row, deleted_at=None).exclude(anonymous="everyone").count(),
            DiscussionReply.objects.filter(thread__course=member.course, author=row, deleted_at=None).exclude(anonymous="everyone").count(),
            DiscussionAnswer.objects.filter(thread__course=member.course, last_editor=row).count(),
            DiscussionThreadState.objects.filter(thread__course=member.course, membership=row, read_at__isnull=False).count()])
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="discussion-statistics.csv"'
    return response
