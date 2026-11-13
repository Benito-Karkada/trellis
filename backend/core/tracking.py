"""Append-only learner events and exact first-open timestamps, starting at deployment."""
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse,Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Membership,Lesson,AssignmentVisit,LearningEvent
from .studio import member


def event(membership,assignment,kind,part=None,metadata=None):
 if membership.role!='student':return None
 return LearningEvent.objects.create(membership=membership,assignment=assignment,part=part,kind=kind,metadata=metadata or {})


@require_POST
@transaction.atomic
def opened(request,assignment_id):
 lesson=get_object_or_404(Lesson,pk=assignment_id,deleted_at=None)
 # Reuse all enrollment, visibility and active-exam restrictions. Before a
 # timed quiz starts, its assignment gate is visible but its questions are not.
 if not request.user.is_authenticated:raise Http404
 membership=get_object_or_404(Membership,user=request.user,course=lesson.course,active=True)
 if lesson.visibility=='staff' and (membership.role=='student' or request.session.get('student_view_course')==lesson.course_id):raise Http404
 if membership.role!='student':return JsonResponse({'ok':True,'recorded':False})
 from .models import QuizAttempt
 locked=QuizAttempt.objects.filter(membership=membership,submitted_at=None,expires_at__gt=timezone.now(),lesson__metadata__exam_mode=True).exclude(lesson=lesson).exists()
 if locked:raise Http404
 visit,_=AssignmentVisit.objects.get_or_create(membership=membership,assignment=lesson,defaults={'last_opened_at':timezone.now()})
 AssignmentVisit.objects.filter(pk=visit.pk).update(last_opened_at=timezone.now(),open_count=F('open_count')+1)
 event(membership,lesson,'assignment_opened')
 return JsonResponse({'ok':True,'recorded':True})
