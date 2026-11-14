"""Authenticated first vertical slice: course navigation, authoring, workspaces."""
import json
from functools import wraps
from pathlib import PurePosixPath
from decimal import Decimal
from django.conf import settings
from django.contrib.auth import login, get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Activity, ActivityFile, Membership, QuizAttempt, Revision, Workspace, ActivityProgress
from .schema import student_projection, validate_content
from .services import require_staff, publish
from .workspace_files import RESULTS_PLACEHOLDER, is_results_file, with_results_placeholder, results_unchanged
from .cooldowns import active_locks


def json_body(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            request.payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'Expected a JSON object.'}, status=400)
        if not isinstance(request.payload, dict):
            return JsonResponse({'error': 'Expected a JSON object.'}, status=400)
        return view(request, *args, **kwargs)
    return wrapped


def valid_path(value):
    return (isinstance(value, str) and 0 < len(value) <= 500
            and '\\' not in value and '\x00' not in value
            and all(part not in {'', '.', '..'} for part in value.split('/')))


def file_visibility(path):
    if path.startswith('grader/'): return 'grader'
    if path.startswith('solutions/'): return 'staff'
    return 'student'


def member(request, activity):
    if not request.user.is_authenticated: raise PermissionDenied
    membership = Membership.objects.filter(user=request.user, course=activity.lesson.course, active=True).first()
    if not membership: raise PermissionDenied
    student_view = not getattr(request,'api_token',None) and request.session.get("student_view_course") == activity.lesson.course_id
    effective_student = membership.role == "student" or student_view
    if activity.lesson.visibility == "staff" and effective_student: raise PermissionDenied
    if effective_student:
        from .honorlock import require_access, is_exam
        require_access(request,activity.lesson,membership)
        quiz_attempt = QuizAttempt.objects.filter(membership=membership, lesson=activity.lesson).first()
        if is_exam(activity.lesson):
            if quiz_attempt is None or quiz_attempt.submitted_at is not None or (quiz_attempt.expires_at and quiz_attempt.expires_at<=timezone.now()): raise PermissionDenied
        locked = QuizAttempt.objects.filter(membership=membership, submitted_at=None,
            lesson__metadata__kind="programming_quiz", lesson__metadata__exam_mode=True,
            expires_at__gt=timezone.now()).select_related("lesson").first()
        if locked and locked.lesson_id != activity.lesson_id: raise PermissionDenied
    return membership


def require_authoring_access(request, course):
    """Require staff permissions without letting student-view escape its projection."""
    if request.session.get("student_view_course") == course.pk:
        raise PermissionDenied
    return require_staff(request.user, course)


def starter_files(revision):
    result = {}
    for f in revision.files.filter(visibility='student'):
        with f.blob.open('rb') as handle:
            result[f.path] = RESULTS_PLACEHOLDER if is_results_file(f.path) else handle.read().decode('utf-8', errors='replace')
    return result


def activity_maximum(activity):
    if not activity.published_revision_id: return '0'
    grading=activity.published_revision.grading
    return point_text(grading.get('maximum_points',1)) if grading.get('definition') or grading.get('questions') else '0'


def point_text(value):
    rendered = format(value, 'f') if hasattr(value, 'as_tuple') else str(value)
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


@ensure_csrf_cookie
def session(request):
    return JsonResponse({'authenticated': request.user.is_authenticated, 'local_login': settings.DEBUG and settings.ALLOW_LOCAL_LOGIN,
                         'registration_open': getattr(settings, 'ALLOW_SELF_REGISTRATION', True),
                         'name': request.user.get_full_name() if request.user.is_authenticated else '',
                         'email': request.user.email if request.user.is_authenticated else '',
                         'student_view': bool(request.session.get('student_view_course'))})


@require_POST
@json_body
def student_view(request):
    if not request.user.is_authenticated: raise PermissionDenied
    membership=Membership.objects.filter(user=request.user,active=True).select_related('course').first()
    if not membership or membership.role not in {'instructor','head_ta','ta'}: raise PermissionDenied
    enabled=request.payload.get('enabled') is True
    if enabled: request.session['student_view_course']=membership.course_id
    else: request.session.pop('student_view_course',None)
    return JsonResponse({'student_view':enabled})


@require_POST
def local_login(request):
    if not settings.DEBUG or not settings.ALLOW_LOCAL_LOGIN: raise Http404
    user = get_object_or_404(get_user_model(), username='studio-instructor')
    login(request, user)
    return JsonResponse({'ok': True})


def outline(request):
    if not request.user.is_authenticated: raise PermissionDenied
    membership = Membership.objects.filter(user=request.user, active=True).select_related('course').first()
    if not membership: raise Http404
    course = membership.course
    student_view=request.session.get('student_view_course') == course.pk
    role='student' if student_view else membership.role
    lesson_query=course.lesson_set.filter(deleted_at=None).select_related('access_config')
    if role=='student':lesson_query=lesson_query.exclude(visibility='staff')
    lesson_rows=list(lesson_query.order_by('position'))
    # Fetch once, without lesson content/files. No per-activity/lesson queries.
    activities=list(Activity.objects.filter(lesson__in=lesson_rows,deleted_at=None)
        .select_related('published_revision').only('id','lesson_id','title','position','metadata',
        'published_revision_id','published_revision__id','published_revision__grading').order_by('position'))
    progress={p.activity_id:p for p in ActivityProgress.objects.filter(user=request.user,
        activity_id__in=[a.pk for a in activities])}
    attempts={a.lesson_id:a for a in QuizAttempt.objects.filter(membership=membership,lesson__in=lesson_rows)}
    by_lesson={lesson.pk:[] for lesson in lesson_rows}
    for activity in activities:by_lesson[activity.lesson_id].append(activity)
    lessons=[]
    resume_candidates=[]
    for lesson in lesson_rows:
        rows=by_lesson[lesson.pk]
        visible=[a for a in rows if a.published_revision_id]
        attempt=attempts.get(lesson.pk) if lesson.metadata.get('kind')=='programming_quiz' else None
        from .honorlock import is_exam, enabled, access_required
        quiz_submitted=bool(role=='student' and attempt and (attempt.submitted_at or attempt.expires_at and attempt.expires_at<=timezone.now()))
        quiz_waiting=bool(role=='student' and lesson.metadata.get('kind')=='programming_quiz'
                          and is_exam(lesson) and (attempt is None or access_required(request,lesson,membership)))
        earned=sum((progress[a.pk].score for a in rows if a.pk in progress),Decimal(0))
        maximum=sum((Decimal(activity_maximum(a)) for a in rows),Decimal(0))
        metadata={**lesson.metadata,'exam_mode':bool(is_exam(lesson)),'honorlock_enabled':enabled(lesson),'attempt_submitted':quiz_submitted,'attempt_started':bool(attempt),
            'earned_points':point_text(earned),'maximum_points':point_text(maximum),
            'activity_count':len(visible),'completed_count':sum(1 for a in visible if a.pk in progress and progress[a.pk].completed)}
        items=[]
        if not quiz_submitted and not quiz_waiting:
            for a in rows:
                if not a.published_revision_id and role not in {'instructor','head_ta','ta'}:continue
                p=progress.get(a.pk)
                items.append({'id':a.pk,'title':a.title,'published':bool(a.published_revision_id),'metadata':a.metadata,
                    'earned_points':point_text(p.score) if p else '0','maximum_points':activity_maximum(a),
                    'status':'completed' if p and p.completed else 'viewed' if p and p.viewed else 'new'})
                if p and p.viewed and a.published_revision_id and lesson.metadata.get('kind') != 'programming_quiz':
                    resume_candidates.append((p.updated_at,{'lesson_id':lesson.pk,'activity_id':a.pk,
                        'lesson_title':lesson.title,'activity_title':a.title,
                        'category':a.metadata.get('category','content')}))
        lessons.append({'id':lesson.pk,'title':lesson.title,'visibility':lesson.visibility,'metadata':metadata,'activities':items})
    resume=max(resume_candidates,key=lambda row:row[0])[1] if resume_candidates else None
    return JsonResponse({'title':course.title,'term':course.term,'role':role,'actual_role':membership.role,
        'student_view':student_view,'lessons':lessons,'resume':resume,'grading_feedback':course.metadata.get('grading_feedback',{})})

def detail(request, pk):
    activity = get_object_or_404(Activity, pk=pk, deleted_at=None, lesson__deleted_at=None)
    member(request, activity)
    staff = request.GET.get('mode') == 'config'
    preview = request.GET.get('mode') == 'preview'
    if staff or preview: require_authoring_access(request, activity.lesson.course)
    revision = activity.revisions.order_by('-number').first() if staff or preview else activity.published_revision
    if revision is None: raise Http404
    data = student_projection(revision)
    if staff:
        data['files'] = list(revision.files.values('id', 'path', 'visibility'))
        data['grading'] = revision.grading
    data.update(title=activity.title, number=revision.number, published_revision=activity.published_revision_id,
                lesson=activity.lesson_id,metadata={**activity.metadata,"placeholder":bool(revision.grading.get("placeholder"))},
                maximum_points=str(revision.grading.get("maximum_points",1)),
                grading_enabled=bool(revision.grading.get("definition")) or bool(revision.grading.get("questions")) and not revision.grading.get("review_required"),
                history=list(activity.revisions.order_by('-number').values('id', 'number', 'created_at')) if staff else [])
    from .ed_discussion import student_link
    data['ed_discussion_url'] = student_link(activity)
    progress = ActivityProgress.objects.filter(user=request.user, activity=activity).first()
    data['earned_points'] = point_text(progress.score) if progress else '0'
    from .visualization import unlocked, samples
    data['visualization_available'] = unlocked(request, revision) and bool(samples(revision))
    from .hints import availability,solved_questions
    data['hints_available']=availability(revision)
    data['solved_questions']=solved_questions(revision,progress)
    from .learning import native_practice,native_reset_available
    data['native_practice']=native_practice(progress)
    data['reset_available']=native_reset_available(revision,progress)
    if progress and progress.question_state and not (staff or preview):
        state={qid:value for qid,value in progress.question_state.items() if qid in revision.grading.get('questions',{}) and 'response' in value}
        data['native_review']={'responses':{qid:v.get('response') for qid,v in state.items()},
            'checks':{qid:v.get('correct',False) for qid,v in state.items()},
            'feedback':{qid:v.get('feedback',[]) for qid,v in state.items()}}

    from .deadlines import effective_due_at,credit_open
    membership=Membership.objects.get(user=request.user,course=activity.lesson.course,active=True)
    due=effective_due_at(membership,activity)
    data['due_at']=due.isoformat() if due else None
    data['practice']=not credit_open(membership,activity)
    if preview:
        data['workspace'] = starter_files(revision)
    elif not staff:
        def initial_files():
            # Publishing revised instructions must not discard a learner's code.
            # Keep earlier workspaces as revision snapshots, and carry work forward.
            prior = Workspace.objects.filter(user=request.user,
                revision__activity=activity, revision__number__lt=revision.number
            ).order_by('-revision__number').first()
            current=starter_files(revision)
            if prior is not None:
                previous=starter_files(prior.revision)
                if not current and not revision.grading and not revision.files.exists():
                    return {path:text for path,text in prior.files.items() if path in previous}
                for path,text in prior.files.items():
                    if path in current and text!=previous.get(path):current[path]=text
            return current
        workspace, _ = Workspace.objects.get_or_create(user=request.user, revision=revision,
                                                      defaults={'files': initial_files})
        data['workspace'] = with_results_placeholder(workspace.files)
        membership = Membership.objects.get(user=request.user, course=activity.lesson.course)
        data['locks'] = {} if native_practice(progress) or (progress and progress.completed and progress.maximum>0 and progress.score>=progress.maximum) else {qid: until.isoformat() for qid, until in active_locks(membership, revision).items()}
    return JsonResponse(data)


@require_POST
@json_body
@transaction.atomic
def edit(request, pk):
    activity = get_object_or_404(Activity.objects.select_for_update(), pk=pk, deleted_at=None)
    require_authoring_access(request, activity.lesson.course)
    body = request.payload
    previous = activity.revisions.order_by('-number').first()
    if previous is None: raise Http404
    if body.get('base_revision') != previous.pk: return JsonResponse({'error': 'This activity changed. Reload before saving.'}, status=409)
    if body.get('action') == 'publish':
        try: publish(activity, previous, request.user)
        except ValidationError as e: return JsonResponse({'error': '; '.join(e.messages)}, status=400)
        return JsonResponse({'ok': True})
    content = body.get('content', previous.content)
    try: validate_content(content)
    except ValidationError as e: return JsonResponse({'error': '; '.join(e.messages)}, status=400)
    files = body.get('files', [])
    if not isinstance(files, list) or len(files) > 1000:
        return JsonResponse({'error': 'Expected a file list.'}, status=400)
    paths = set()
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get('text'), str) or not valid_path(f.get('path')):
            return JsonResponse({'error': 'Invalid file.'}, status=400)
        if f['path'] in paths:
            return JsonResponse({'error': 'Use unique relative file paths.'}, status=400)
        if len(f['text'].encode()) > 1024 * 1024: return JsonResponse({'error': 'File is too large.'}, status=400)
        paths.add(f['path'])
    grading=body.get("grading",previous.grading)
    from decimal import InvalidOperation
    try:
        maximum=Decimal(str(grading.get("maximum_points",1)))
        if not maximum.is_finite() or not 0<=maximum<=10000:raise ValueError()
    except (ValueError,InvalidOperation,AttributeError):
        return JsonResponse({"error":"Enter points between 0 and 10000."},status=400)
    revision = Revision.objects.create(activity=activity, number=previous.number + 1, content=content,
                                       grading=grading, created_by=request.user)
    import hashlib
    for f in files:
        raw = f['text'].encode()
        ActivityFile.objects.create(revision=revision, path=f['path'], visibility=file_visibility(f['path']),
            blob=ContentFile(raw, name=PurePosixPath(f['path']).name), sha256=hashlib.sha256(raw).hexdigest())
    return JsonResponse({'ok': True, 'revision': revision.pk})


def file_text(request, pk):
    file = get_object_or_404(ActivityFile, pk=pk, revision__activity__deleted_at=None,
                            revision__activity__lesson__deleted_at=None)
    member(request, file.revision.activity)
    if request.GET.get('mode') in {'config', 'preview'}:
        require_authoring_access(request, file.revision.activity.lesson.course)
    elif file.revision_id != file.revision.activity.published_revision_id: raise Http404
    if file.visibility != 'student' and request.GET.get('mode') != 'config': raise Http404
    with file.blob.open('rb') as handle: text = handle.read().decode('utf-8', errors='replace')
    return JsonResponse({'text': text})


@require_POST
@json_body
@transaction.atomic
def save_workspace(request, pk):
    revision = get_object_or_404(Revision, pk=pk, activity__deleted_at=None, activity__lesson__deleted_at=None)
    member(request, revision.activity)
    if revision.pk != revision.activity.published_revision_id: require_authoring_access(request, revision.activity.lesson.course)
    # Lock the owner's account so reset/save and first-workspace creation serialize.
    get_user_model().objects.select_for_update().get(pk=request.user.pk)
    workspace, _ = Workspace.objects.get_or_create(user=request.user, revision=revision,
                                                  defaults={'files': lambda: starter_files(revision)})
    if request.payload.get('action') == 'reset':
        from .models import ExecutionJob
        if ExecutionJob.objects.filter(user=request.user, revision=revision, status__in=['pending', 'running']).exists():
            return JsonResponse({'error': 'Wait for your queued or running code to finish before resetting the workspace.'}, status=409)
        workspace.files = starter_files(revision)
        workspace.generation += 1
        workspace.save(update_fields=['files', 'updated_at','generation'])
        return JsonResponse({'ok': True, 'workspace': workspace.files})
    files = request.payload.get('files')
    if not isinstance(files, dict) or len(json.dumps(files)) > 2 * 1024 * 1024: return JsonResponse({'error': 'Invalid workspace'}, status=400)
    if any(not valid_path(k) or not isinstance(v, str) for k,v in files.items()):
        return JsonResponse({'error': 'Invalid file'}, status=400)
    protected = with_results_placeholder(workspace.files)
    if not results_unchanged(files, protected):
        return JsonResponse({'error': 'full_results.txt is read-only and is updated when you submit.'}, status=403)
    if set(files) != set(workspace.files):
        return JsonResponse({'error': 'Files cannot be added, removed, or renamed in a student workspace.'}, status=400)
    workspace.files = files
    workspace.generation += 1
    workspace.save(update_fields=['files', 'updated_at','generation'])
    return JsonResponse({'ok': True})


@require_POST
@json_body
def check_answer(request, pk):
    revision = get_object_or_404(Revision, pk=pk, activity__deleted_at=None, activity__lesson__deleted_at=None)
    member(request, revision.activity)
    if revision.pk != revision.activity.published_revision_id: require_staff(request.user, revision.activity.lesson.course)
    body = request.payload
    if not isinstance(body.get('question'), str) or not isinstance(body.get('choice'), str):
        return JsonResponse({'error': 'Choose an answer first.'}, status=400)
    question = revision.grading.get('questions', {}).get(body.get('question'))
    if question is None: raise Http404
    return JsonResponse({'correct': [body.get('choice')] == question.get('correct_choice_ids')})
