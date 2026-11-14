from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from celery import shared_task
from .models import GradeEvent


@shared_task
def refresh_discussion_search(thread_id):
    """Generate all search documents for a post outside the web request."""
    from .discussion_search import refresh_thread_index
    refresh_thread_index(thread_id)

@shared_task(bind=True, max_retries=10)
def pass_grade_to_canvas(self, grade_event_id):
    """Event-driven AGS handoff. The OAuth/HTTP adapter is intentionally pending."""
    with transaction.atomic():
        event = GradeEvent.objects.select_for_update().get(pk=grade_event_id)
        if event.status == "sent": return
        event.attempts += 1
        try:
            _send_ags_score(event)
        except Exception as exc:
            delay = min(15 * (2 ** (event.attempts - 1)), 3600)
            event.status = "retrying"
            event.last_error = str(exc)[:2000]
            event.next_attempt_at = timezone.now() + timedelta(seconds=delay)
            event.save(update_fields=["attempts", "status", "last_error", "next_attempt_at"])
            raise self.retry(exc=exc, countdown=delay)
        event.status = "sent"
        event.last_error = ""
        event.next_attempt_at = None
        event.save(update_fields=["attempts", "status", "last_error", "next_attempt_at"])

def _send_ags_score(event):
    raise RuntimeError("Configure the validated LTI 1.3 AGS adapter before enabling passback")
