"""Anti-brute-force retry cooldown for non-coding question submissions.

Kept separate from learning.py/studio.py so both can share it without an import cycle.
"""
from django.utils import timezone
from .models import QuestionCooldown

RETRY_COOLDOWN_SECONDS = 120


def active_locks(membership, revision):
    """Question ids currently in cooldown for this membership+revision, mapped to when they unlock."""
    return {
        cooldown.question_id: cooldown.locked_until
        for cooldown in QuestionCooldown.objects.filter(membership=membership, revision=revision, locked_until__gt=timezone.now())
    }
