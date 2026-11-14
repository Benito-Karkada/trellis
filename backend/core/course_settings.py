"""Staff roster, Canvas sync, and programming-quiz accommodations APIs."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import io
import os
import time
import secrets
from uuid import uuid4
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
import jwt
import requests

from .models import Accommodation, CanvasResourceLink, Course, Lesson, LTIIdentity, Membership
from .services import require_staff
from .studio import json_body


ALLOWED_ROLES = {"student", "ta", "instructor"}
NRPS_SCOPE = "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"


def staff_course(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    from .course_context import current_membership
    membership = current_membership(request)
    if membership.role not in {'instructor', 'head_ta', 'ta'}:
        raise PermissionDenied
    if request.session.get("student_view_course") == membership.course_id:
        raise PermissionDenied
    return membership.course


def instructor_course(request):
    course = staff_course(request)
    if not Membership.objects.filter(user=request.user, course=course, active=True, role="instructor").exists():
        raise PermissionDenied("Only instructors can manage course administration.")
    return course


def clean_email(value):
    email = str(value or "").strip().casefold()
    validate_email(email)
    return email


def split_name(name):
    pieces = str(name or "").strip().split(None, 1)
    return (pieces[0][:150] if pieces else "", pieces[1][:150] if len(pieces) > 1 else "")


@transaction.atomic
def enroll(course, email, role, *, name="", source="manual"):
    if role not in ALLOWED_ROLES:
        raise ValidationError("Choose a valid course role.")
    email = clean_email(email)
    users = get_user_model().objects.select_for_update()
    user = users.filter(username__iexact=email).first() or users.filter(email__iexact=email).first()
    created = user is None
    if user is None:
        first_name, last_name = split_name(name)
        user = get_user_model()(username=email, email=email, first_name=first_name, last_name=last_name)
        user.set_unusable_password()
        user.save()
    membership, membership_created = Membership.objects.get_or_create(
        course=course, user=user, defaults={"role": role, "source": source, "active": True}
    )
    if not membership_created:
        membership.role = role
        membership.active = True
        if source == "canvas" and membership.source == "canvas":
            membership.source = source
        membership.save(update_fields=["role", "active", "source"])
    return membership, created or membership_created


def serialize_member(membership):
    user = membership.user
    return {
        "id": membership.pk,
        "email": user.email or user.username,
        "name": user.get_full_name(),
        "role": membership.role,
        "active": membership.active,
        "source": membership.source,
        "account_ready": user.has_usable_password(),
    }


def decimal_text(value):
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def roster(request):
    course = staff_course(request)
    rows = Membership.objects.filter(course=course).select_related("user").order_by("role", "user__email")
    can_manage_logins = Membership.objects.filter(course=course,user=request.user,active=True,role='instructor').exists() and request.session.get('student_view_course') != course.pk
    return JsonResponse({"course": course.title, "members": [serialize_member(row) for row in rows], "can_manage_logins":can_manage_logins,"current_member_id":Membership.objects.get(course=course,user=request.user).pk})


@require_POST
@json_body
@transaction.atomic
def provision_login(request, pk):
    course = staff_course(request)
    if (request.session.get('student_view_course') == course.pk or not
            Membership.objects.filter(course=course,user=request.user,active=True,role='instructor').exists()):
        raise PermissionDenied
    membership=get_object_or_404(Membership.objects.select_related('user'),pk=pk,course=course,active=True)
    user=get_user_model().objects.select_for_update().get(pk=membership.user_id)
    if user.pk==request.user.pk or user.is_superuser:
        return JsonResponse({'error':'Use your own account settings to change this password.'},status=400)
    if user.has_usable_password() and request.payload.get('reset') is not True:
        return JsonResponse({'error':'This login already exists. Confirm a password reset to replace it.'},status=409)
    password=request.payload.get('password') or secrets.token_urlsafe(12)
    if not isinstance(password,str):return JsonResponse({'error':'Enter a valid password.'},status=400)
    try:validate_password(password,user=user)
    except ValidationError as exc:return JsonResponse({'error':' '.join(exc.messages)},status=400)
    user.set_password(password);user.is_active=True;user.save(update_fields=['password','is_active'])
    response=JsonResponse({'email':user.email or user.username,'password':password,'role':membership.role})
    response['Cache-Control']='no-store'
    return response


@require_POST
@json_body
def add_enrollment(request):
    course = instructor_course(request)
    try:
        membership, created = enroll(
            course,
            request.payload.get("email"),
            str(request.payload.get("role", "student")),
            name=request.payload.get("name", ""),
        )
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    return JsonResponse({"created": created, "member": serialize_member(membership)})


def csv_rows(upload):
    if upload.size > 2 * 1024 * 1024:
        raise ValidationError("CSV files must be smaller than 2 MB.")
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("CSV files must use UTF-8 text.")
    raw = list(csv.reader(io.StringIO(text)))
    if not raw:
        return []
    header = [cell.strip().casefold() for cell in raw[0]]
    if "email" in header or "email address" in header:
        email_index = header.index("email") if "email" in header else header.index("email address")
        name_index = next((header.index(key) for key in ("name", "full name") if key in header), None)
        data = raw[1:]
    else:
        email_index, name_index, data = 0, 1 if len(raw[0]) > 1 else None, raw
    return [
        (row[email_index].strip(), row[name_index].strip() if name_index is not None and len(row) > name_index else "")
        for row in data if len(row) > email_index and row[email_index].strip()
    ]


@require_POST
def import_enrollments(request):
    course = instructor_course(request)
    upload = request.FILES.get("file")
    role = request.POST.get("role", "student")
    if upload is None:
        return JsonResponse({"error": "Choose a CSV file."}, status=400)
    if role not in ALLOWED_ROLES:
        return JsonResponse({"error": "Choose a valid course role."}, status=400)
    try:
        rows = csv_rows(upload)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    if len(rows) > 5000:
        return JsonResponse({"error": "A CSV can contain at most 5,000 people."}, status=400)
    added = updated = 0
    errors = []
    for line, (email, name) in enumerate(rows, 2):
        try:
            _, created = enroll(course, email, role, name=name)
            added += int(created)
            updated += int(not created)
        except ValidationError:
            errors.append({"line": line, "email": email, "error": "Invalid email address"})
    return JsonResponse({"added": added, "updated": updated, "errors": errors[:100]})


def canvas_access_token(registration):
    private_key = os.environ.get("LTI_PRIVATE_KEY", "").replace("\\n", "\n")
    key_file = os.environ.get("LTI_PRIVATE_KEY_FILE", "")
    if not private_key and key_file:
        private_key = open(key_file).read()
    key_id = registration.key_id or os.environ.get("LTI_KEY_ID", "")
    if not private_key or not key_id:
        raise ValidationError("Canvas roster sync needs the LTI private key and key ID in server settings.")
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": registration.client_id, "sub": registration.client_id, "aud": registration.token_url,
         "iat": now, "exp": now + 300, "jti": str(uuid4())},
        private_key, algorithm="RS256", headers={"kid": key_id},
    )
    response = requests.post(
        registration.token_url,
        data={"grant_type": "client_credentials", "client_assertion_type":
              "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
              "client_assertion": assertion, "scope": NRPS_SCOPE},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def canvas_role(roles):
    joined = " ".join(roles or []).casefold()
    if "instructor" in joined or "faculty" in joined:
        return "instructor"
    if "teachingassistant" in joined or "teaching assistant" in joined:
        return "ta"
    if "learner" in joined or "student" in joined:
        return "student"
    return None


@require_POST
@transaction.atomic
def sync_canvas_roster(request):
    course = instructor_course(request)
    link = CanvasResourceLink.objects.filter(course=course).exclude(nrps_memberships_url="").order_by("-pk").first()
    if course.lti_registration is None or link is None:
        return JsonResponse({"error": "Launch this course from Canvas after its LTI registration is connected."}, status=409)
    try:
        token = canvas_access_token(course.lti_registration)
        original_host = urlparse(link.nrps_memberships_url).hostname
        url = link.nrps_memberships_url
        people = []
        for _ in range(100):
            if urlparse(url).scheme != "https" or urlparse(url).hostname != original_host:
                raise ValidationError("Canvas returned an unsafe roster page URL.")
            response = requests.get(url, headers={"Authorization": "Bearer " + token,
                "Accept": "application/vnd.ims.lti-nrps.v2.membershipcontainer+json"}, timeout=30)
            response.raise_for_status()
            people.extend(response.json().get("members", []))
            url = response.links.get("next", {}).get("url")
            if not url:
                break
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=409)
    except (requests.RequestException, KeyError, ValueError):
        return JsonResponse({"error": "Canvas roster sync failed. Check the LTI service configuration and try again."}, status=502)

    seen, added, updated, skipped = set(), 0, 0, 0
    for person in people:
        role = canvas_role(person.get("roles"))
        email = person.get("email")
        if not role or not email:
            skipped += 1
            continue
        try:
            membership, created = enroll(course, email, role, name=person.get("name", ""), source="canvas")
        except ValidationError:
            skipped += 1
            continue
        seen.add(membership.pk)
        added += int(created)
        updated += int(not created)
        subject = str(person.get("user_id", ""))
        if subject:
            LTIIdentity.objects.update_or_create(
                registration=course.lti_registration, subject=subject, defaults={"user": membership.user}
            )
    deactivated = Membership.objects.filter(course=course, source="canvas", active=True).exclude(pk__in=seen).update(active=False)
    return JsonResponse({"added": added, "updated": updated, "deactivated": deactivated, "skipped": skipped})


def accommodation_data(request):
    course = staff_course(request)
    scope = request.GET.get("activity", "")
    lesson = None
    if scope.startswith("quiz:"):
        lesson = get_object_or_404(Lesson, pk=scope.removeprefix("quiz:"), course=course, deleted_at=None, metadata__kind="programming_quiz")
    elif scope:
        return JsonResponse({"error": "Choose a programming quiz."}, status=400)
    students = Membership.objects.filter(course=course, role="student", active=True).select_related("user")
    accommodations = Accommodation.objects.filter(membership__course=course, activity=None, lesson=lesson)
    by_member = {row.membership_id: row for row in accommodations}
    course_defaults = ({row.membership_id: row for row in Accommodation.objects.filter(
        membership__course=course, activity=None, lesson=None
    )} if lesson else {})
    rows = []
    timed = lesson
    base_minutes = Decimal(str(timed.metadata.get("time_limit_minutes", 0))) if timed else Decimal(0)
    for student in students:
        value = by_member.get(student.pk) or course_defaults.get(student.pk)
        multiplier = value.time_multiplier if value else Decimal(1)
        extra = value.extra_minutes if value else 0
        rows.append({**serialize_member(student), "time_percent": decimal_text(multiplier * 100),
                     "extra_minutes": extra, "extra_attempts": value.extra_attempts if value else 0,
                     "effective_minutes": decimal_text(base_minutes * multiplier + extra) if base_minutes else None,
                     "inherited": bool(timed and student.pk not in by_member and student.pk in course_defaults)})
    quiz_scopes = [{"id": f"quiz:{item.pk}", "title": item.title, "lesson": "Programming quizzes",
                    "time_limit_minutes": item.metadata.get("time_limit_minutes"), "exam_mode": bool(item.metadata.get("exam_mode"))}
                   for item in Lesson.objects.filter(course=course, deleted_at=None, metadata__kind="programming_quiz").order_by("position")]
    return JsonResponse({"students": rows, "activities": quiz_scopes})


@require_POST
@json_body
@transaction.atomic
def save_accommodations(request):
    course = instructor_course(request)
    member_ids = request.payload.get("membership_ids", [])
    if not isinstance(member_ids, list) or not member_ids or len(member_ids) > 5000:
        return JsonResponse({"error": "Choose at least one student."}, status=400)
    scope = str(request.payload.get("activity_id") or "")
    lesson = None
    if scope.startswith("quiz:"):
        lesson = get_object_or_404(Lesson, pk=scope.removeprefix("quiz:"), course=course, deleted_at=None, metadata__kind="programming_quiz")
    elif scope:
        return JsonResponse({"error": "Choose a programming quiz."}, status=400)
    try:
        percent = Decimal(str(request.payload.get("time_percent", 100)))
        extra_minutes = int(request.payload.get("extra_minutes", 0))
        extra_attempts = int(request.payload.get("extra_attempts", 0))
        if not percent.is_finite() or not 100 <= percent <= 1000 or not 0 <= extra_minutes <= 10080 or not 0 <= extra_attempts <= 100:
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({"error": "Use 100–1000% time and valid nonnegative extras."}, status=400)
    students = list(Membership.objects.filter(pk__in=member_ids, course=course, role="student", active=True))
    if len(students) != len(set(member_ids)):
        return JsonResponse({"error": "One or more selected students are invalid."}, status=400)
    for student in students:
        Accommodation.objects.update_or_create(membership=student, activity=None, lesson=lesson, defaults={
            "time_multiplier": percent / 100, "extra_minutes": extra_minutes, "extra_attempts": extra_attempts,
        })
    return JsonResponse({"updated": len(students)})


@require_POST
@json_body
@transaction.atomic
def remove_enrollment(request, pk):
    course = staff_course(request)
    if request.session.get('student_view_course') == course.pk or not Membership.objects.filter(course=course, user=request.user, active=True, role='instructor').exists():
        raise PermissionDenied
    # Serialize with roster writers; dropping a membership preserves its records.
    Course.objects.select_for_update().get(pk=course.pk)
    membership = get_object_or_404(Membership.objects.select_for_update(), pk=pk, course=course)
    if membership.user_id == request.user.pk:
        return JsonResponse({'error': 'You cannot remove your own enrollment.'}, status=400)
    membership.active = False
    membership.save(update_fields=['active'])
    from .models import APIAuditEvent
    APIAuditEvent.objects.create(course=course,actor=request.user,request_id=uuid4(),method='POST',path=request.path,status=200,summary={'enrollment_id':membership.pk,'active':False,'role':membership.role})
    return JsonResponse({'removed': True, 'member': serialize_member(membership)})
