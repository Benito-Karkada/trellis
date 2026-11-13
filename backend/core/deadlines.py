"""Credit deadlines are evaluated at receipt time, never at worker completion."""
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Accommodation


def effective_due_at(membership, activity, accommodations=None):
    if accommodations is None:
        override=(Accommodation.objects.filter(membership=membership,activity=activity,due_at_override__isnull=False).first()
            or Accommodation.objects.filter(membership=membership,lesson=activity.lesson,due_at_override__isnull=False).first()
            or Accommodation.objects.filter(membership=membership,activity=None,lesson=None,due_at_override__isnull=False).first())
    else:
        override=(next((a for a in accommodations if a.activity_id==activity.pk),None)
            or next((a for a in accommodations if a.lesson_id==activity.lesson_id),None)
            or next((a for a in accommodations if a.activity_id is None and a.lesson_id is None),None))
    if override:return override.due_at_override
    raw=activity.metadata.get('due_at') or activity.lesson.metadata.get('due_at')
    if not raw:return None
    due=parse_datetime(raw)
    # Invalid legacy values must not silently grant late credit.
    if due is None or timezone.is_naive(due):raise ValueError('Invalid assignment deadline')
    return due


def credit_open(membership, activity, received_at=None):
    due=effective_due_at(membership,activity)
    return due is None or (received_at or timezone.now()) <= due
