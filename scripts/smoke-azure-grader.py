"""Live HTTPS -> PostgreSQL queue -> Azure VM -> results integration checks.

Creates a temporary student/course and private files, then removes them. Never
uses real students' work or alters real course grades. Requires Azure CLI access.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import requests

ROOT = Path(__file__).resolve().parents[1]


def maintenance(source):
    with tempfile.TemporaryDirectory(prefix="trellis-smoke-") as folder:
        path = Path(folder) / "maintenance.py"
        path.touch(mode=0o600)
        path.write_text(source)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/azure-private-exec.py"),
                                 "--python-file", str(path)], capture_output=True, text=True)
        if result.returncode or "CS1301_MAINTENANCE_DONE" not in result.stdout:
            raise RuntimeError("Private maintenance failed")
        return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    suffix = uuid4().hex[:20]
    email = "runner-check-" + suffix + "@example.invalid"
    password = secrets.token_urlsafe(32)
    term = "runner-check-" + suffix
    setup = '''import django, json, hashlib
django.setup()
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from core.models import Course, Membership, Lesson, Activity, Revision, ActivityFile
with transaction.atomic():
    user=get_user_model().objects.create_user(username=EMAIL,email=EMAIL,password=PASSWORD)
    course=Course.objects.create(title='Temporary execution verification',term=TERM)
    Membership.objects.create(user=user,course=course,role='student')
    result={}
    for kind in ('coding','sandbox','quiz'):
        lesson=Lesson.objects.create(course=course,title='Verification '+kind,metadata={'kind':'programming_quiz','exam_mode':True,'time_limit_minutes':10} if kind=='quiz' else {})
        activity=Activity.objects.create(lesson=lesson,title='Verification '+kind,metadata={'kind':'coding','sandbox':kind=='sandbox'})
        revision=Revision.objects.create(activity=activity,number=1,created_by=user,content={'version':1,'blocks':[]},grading={'entrypoint':'main.py','maximum_points':'7.5','definition':{'version':1,'cases':[{'id':'value','label':'Value','target':'answer','expected':5}]}})
        activity.published_revision=revision;activity.save()
        hidden=None
        for path,text,visibility in [('main.py','', 'student'),('full_results.txt','', 'student'),('sample_answer.py','', 'student')] + [('solutions/sample_answer.py','answer = 5\\n','staff')]:
            file=ActivityFile.objects.create(revision=revision,path=path,visibility=visibility,sha256=hashlib.sha256(text.encode()).hexdigest(),blob=ContentFile(text.encode(),name=path.split('/')[-1]))
            if visibility=='staff':hidden=file.pk
        result[kind]={'activity':activity.pk,'revision':revision.pk,'lesson':lesson.pk,'hidden':hidden}
print('TRELLIS_FIXTURE:'+json.dumps(result),flush=True)
'''.replace("EMAIL", repr(email)).replace("PASSWORD", repr(password)).replace("TERM", repr(term))
    cleanup = '''import django
django.setup()
from django.contrib.auth import get_user_model
from core.models import Course, Activity, Revision, ExecutionJob, Workspace, ActivityProgress, Submission, QuizAttempt, Accommodation, ActivityFile, Membership
course=Course.objects.filter(term=TERM).first()
if course:
    revisions=Revision.objects.filter(activity__lesson__course=course)
    files=list(ActivityFile.objects.filter(revision__in=revisions))
    ExecutionJob.objects.filter(revision__in=revisions).delete()
    Submission.objects.filter(revision__in=revisions).delete()
    Workspace.objects.filter(revision__in=revisions).delete()
    ActivityProgress.objects.filter(activity__lesson__course=course).delete()
    QuizAttempt.objects.filter(lesson__course=course).delete()
    Accommodation.objects.filter(membership__course=course).delete()
    Activity.objects.filter(lesson__course=course).update(published_revision=None)
    revisions.delete()
    Activity.objects.filter(lesson__course=course).delete()
    course.lesson_set.all().delete()
    Membership.objects.filter(course=course).delete()
    course.delete()
    for file in files:file.blob.delete(save=False)
get_user_model().objects.filter(username=EMAIL,email=EMAIL).delete()
print('Temporary verification data removed.',flush=True)
'''.replace("EMAIL", repr(email)).replace("TERM", repr(term))
    session = requests.Session()

    def post(path, body):
        return session.post(base + path, json=body, headers={
            "X-CSRFToken": session.cookies.get("csrftoken", ""), "Referer": base + "/"}, timeout=30)

    def detail(item):
        response=session.get(base + f"/api/studio/{item['activity']}/", timeout=30)
        response.raise_for_status()
        return response.json()

    def execute(item, source, operation="submit"):
        files=detail(item)["workspace"]
        files["main.py"]=source
        response=post(f"/api/execute/{item['revision']}/", {"operation":operation,"entrypoint":"main.py","files":files})
        assert response.status_code==200, f"Queue rejected: {response.status_code}"
        job=response.json()["id"]
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            response=session.get(base+f"/api/jobs/{job}/",timeout=30)
            response.raise_for_status()
            state=response.json()
            if state["status"] in {"completed","failed"}:
                assert state["status"]=="completed", "Worker reported a service failure"
                return state["result"]
            time.sleep(1)
        raise AssertionError("Worker did not complete the attempt in time")

    try:
        output=maintenance(setup)
        fixture=json.loads(output.split("TRELLIS_FIXTURE:",1)[1].splitlines()[0])
        session.get(base+"/api/session/",timeout=30).raise_for_status()
        assert post("/api/auth/login/",{"email":email,"password":password}).status_code==200
        coding=fixture["coding"]
        assert session.get(base+f"/api/studio/{coding['activity']}/?mode=config",timeout=30).status_code==403
        assert session.get(base+f"/api/files/{coding['hidden']}/",timeout=30).status_code in {403,404}
        assert execute(coding,'print("Trellis Azure execution works")',"run")["stdout"]=="Trellis Azure execution works\n"
        assert "NameError" in execute(coding,"print(undefined_name)","run")["stdout"]
        assert execute(coding,"while True: pass","run")["execution_status"]=="timeout"
        assert execute(coding,"import os\nwhile True: os.write(1,b'x'*8192)","run")["execution_status"]=="output_limit"
        print("Run, Python errors, timeouts and output limits: OK",flush=True)
        wrong=execute(coding,"answer = 4")
        assert wrong["passed"] is False and wrong["score"]=="0" and wrong["maximum"]=="7.5"
        workspace=detail(coding)["workspace"]
        assert workspace["full_results.txt"] and workspace["sample_answer.py"]==""
        correct=execute(coding,"answer = (lambda: 5)()")
        assert correct["passed"] is True and correct["score"]=="7.5"
        state=detail(coding)
        assert state["earned_points"]=="7.5" and state["workspace"]["sample_answer.py"]=="answer = 5\n"
        assert state["workspace"]["full_results.txt"]==correct["workspace_files"]["full_results.txt"]
        assert post(f"/api/workspaces/{coding['revision']}/",{"action":"reset"}).status_code==200
        assert detail(coding)["workspace"]=={"main.py":"","full_results.txt":"Submit your code to see your test results here.\n","sample_answer.py":""}
        print("Wrong/correct grading, points, feedback, sample file replacement and reset: OK",flush=True)
        verification = """import django
django.setup()
from core.models import ExecutionJob
job=ExecutionJob.objects.filter(user__username=EMAIL,revision__activity__lesson__course__term=TERM,operation='submit',preview=False).order_by('-created_at').first()
assert any(flag.get('name')=='lambda' for flag in job.review_signals.get('flags',[]))
assert job.result['score']=='7.5'
print('Private code observations recorded; grading remains independent.',flush=True)
""".replace('EMAIL',repr(email)).replace('TERM',repr(term))
        maintenance(verification)
        print("Private review observations and unchanged grading: OK",flush=True)
        sandbox=fixture["sandbox"]
        assert execute(sandbox,"print(123)","run")["stdout"]=="123\n"
        response=post(f"/api/execute/{sandbox['revision']}/",{"operation":"submit","files":detail(sandbox)["workspace"]})
        assert response.status_code==400
        quiz=fixture["quiz"]
        assert post(f"/api/quizzes/{quiz['lesson']}/start/",{}).status_code==200
        assert execute(quiz,"answer = 4")["passed"] is False
        assert execute(quiz,"answer = 5")["passed"] is True
        assert detail(quiz)["workspace"]["sample_answer.py"]==""
        assert post(f"/api/quizzes/{quiz['lesson']}/finish/",{}).status_code==200
        assert session.get(base+f"/api/studio/{quiz['activity']}/",timeout=30).status_code==403
        print("Sandbox Run-only, quiz retries, staff-only samples and closed-quiz access: OK",flush=True)
    finally:
        try:
            post('/api/auth/logout/', {})
        except requests.RequestException:
            pass
        session.close()
        maintenance(cleanup)
        print("Temporary student/course/files removed.",flush=True)


if __name__=="__main__":
    main()
