from django.http import JsonResponse, Http404
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from .models import Activity
from .services import require_staff
from .schema import student_projection
from .cooldowns import active_locks
from .studio import member, require_authoring_access

def health(request): return JsonResponse({"status": "ok"})

@login_required
def student_activity(request, pk):
    activity = get_object_or_404(Activity, pk=pk, deleted_at=None, lesson__deleted_at=None)
    membership = member(request, activity)
    if not activity.published_revision_id: raise Http404
    payload = student_projection(activity.published_revision)
    payload["locks"] = {qid: until.isoformat() for qid, until in active_locks(membership, activity.published_revision).items()}
    return JsonResponse(payload)

@login_required
def preview_activity(request, pk):
    activity = get_object_or_404(Activity, pk=pk, deleted_at=None)
    require_authoring_access(request, activity.lesson.course)
    revision = activity.revisions.order_by("-number").first()
    if revision is None: raise Http404
    return JsonResponse(student_projection(revision))
