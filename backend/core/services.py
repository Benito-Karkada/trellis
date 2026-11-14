from django.db import transaction
from django.core.exceptions import PermissionDenied, ValidationError
from uuid import uuid4
from .models import Activity, Membership, Revision
from .schema import validate_content

def require_staff(user, course):
    if not user.is_authenticated:
        raise PermissionDenied
    if not Membership.objects.filter(user=user, course=course, active=True, role__in=["instructor", "head_ta", "ta"]).exists():
        raise PermissionDenied

@transaction.atomic
def save_revision(activity, user, content, grading):
    activity = Activity.objects.select_for_update().get(pk=activity.pk)
    require_staff(user, activity.lesson.course)
    validate_content(content)
    last = activity.revisions.order_by("-number").first()
    return Revision.objects.create(activity=activity, number=last.number + 1 if last else 1, content=content, grading=grading, created_by=user)

@transaction.atomic
def publish(activity, revision, user):
    require_staff(user, activity.lesson.course)
    if revision.activity_id != activity.pk or activity.deleted_at:
        raise ValidationError("Invalid revision or deleted activity")
    validate_content(revision.content)
    if revision.files.filter(visibility="quarantine").exists():
        raise ValidationError("Classify all exercise files before publishing")
    activity.published_revision = revision
    activity.save(update_fields=["published_revision"])

@transaction.atomic
def record_grade(submission, score, maximum, idempotency_key=None):
    """Persist a grade event and enqueue Canvas passback only after commit."""
    from .models import GradeEvent
    from .tasks import pass_grade_to_canvas

    key = idempotency_key or uuid4()
    event, created = GradeEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={"submission": submission, "score": score, "maximum": maximum},
    )
    if not created and (event.submission_id != submission.pk or event.score != score or event.maximum != maximum):
        raise ValidationError("Idempotency key was already used for a different grade")
    if created:
        transaction.on_commit(lambda: pass_grade_to_canvas.delay(event.pk))
    return event
