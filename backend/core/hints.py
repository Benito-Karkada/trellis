"""Explicit student-facing hints; never return correctness or private grading data."""
import json
from django.http import JsonResponse,Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from .models import Revision
from .studio import member,json_body,require_authoring_access


def general_hints(revision):
    return list(revision.grading.get('hints', []))[:50]


def availability(revision):
    return {'general': bool(revision.grading.get('hints')), 'questions': [
        qid for qid, rule in revision.grading.get('questions', {}).items()
        if any(rule.get('choice_feedback', {}).values())
        or any(rule.get('choice_feedback_rules', {}).values()) or rule.get('hints')
    ]}


def solved_questions(revision,progress):
    if not progress:return []
    rules=revision.grading.get('questions',{})
    # Existing full-credit activity records predate per-question review tracking.
    if not progress.question_state and progress.completed and progress.maximum>0 and progress.score>=progress.maximum:return list(rules)
    return [qid for qid,value in progress.question_state.items() if qid in rules and value.get('solved')]


@require_POST
@json_body
def reveal(request,pk):
    revision=get_object_or_404(Revision,pk=pk,activity__deleted_at=None,activity__lesson__deleted_at=None)
    member(request,revision.activity)
    preview=request.payload.get('preview') is True
    if preview:require_authoring_access(request,revision.activity.lesson.course)
    elif revision.pk!=revision.activity.published_revision_id:raise Http404
    qid=request.payload.get('question_id')
    if not isinstance(qid,str) or qid not in revision.grading.get('questions',{}):raise Http404
    rule=revision.grading['questions'][qid]
    kind=request.payload.get('kind','general')
    if kind=='general':
        # General demand hints are distinct from answer-choice explanations.
        # Ignore any supplied response so this cannot be used to inspect answers.
        hints=general_hints(revision)+list(rule.get('hints',[]))
    elif kind=='choice':
        from .models import ActivityProgress
        progress=ActivityProgress.objects.filter(user=request.user,activity=revision.activity).first()
        if not preview and qid not in solved_questions(revision,progress):
            return JsonResponse({'error':'Submit a correct answer before exploring other answer explanations.'},status=403)
        choice=request.payload.get('choice_id')
        valid={c['id'] for block in revision.content['blocks'] if block['id']==qid for c in block.get('choices',[])}
        if not isinstance(choice,str) or choice not in valid:return JsonResponse({'error':'Choose one of the available answers.'},status=400)
        if 'choice_feedback_rules' in rule:
            entries=rule['choice_feedback_rules'].get(choice,[])
            selected=[h['content'] for h in entries if h.get('selected') is True and h.get('content')]
            hints=selected or [h['content'] for h in entries if h.get('content')]
        else:
            content=rule.get('choice_feedback',{}).get(choice,[])
            hints=[content] if content else []
    else:return JsonResponse({'error':'Unknown hint request.'},status=400)
    seen=set();unique=[]
    for hint in hints:
        key=json.dumps(hint,sort_keys=True)
        if key not in seen:unique.append(hint);seen.add(key)
    response=JsonResponse({'hints':unique});response['Cache-Control']='no-store';return response
