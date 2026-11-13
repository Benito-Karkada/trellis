"""Import prepared programming quiz archives into timed course assessments."""
import ast
import hashlib
import json
import re
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import Activity, ActivityFile, Course, Lesson, Membership, Revision


def prompt_from_source(source):
    lines=[]
    for line in source.splitlines():
        stripped=line.strip()
        if stripped.startswith("#"):
            text=stripped.lstrip("#").strip()
            if text and not any(phrase in text.casefold() for phrase in ("you may modify", "do not move it", "write your code here")):
                lines.append(text)
    text=" ".join(lines)
    text=re.sub(r"\s+", " ", text).strip()
    return text or "Complete the Python program using the provided code and submit it for grading."


def scaffold(source, filename):
    """Remove answers from an accidentally exported sample-answer workspace."""
    if filename != "sample_answer_1.py": return source
    tree=ast.parse(source)
    nodes=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            node.body=[ast.Expr(value=ast.Constant(value="Complete this function.")),ast.Pass()]
            nodes.append(node)
        elif isinstance(node,ast.ClassDef):
            for child in node.body:
                if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    child.body=[ast.Expr(value=ast.Constant(value="Complete this method.")),ast.Pass()]
            nodes.append(node)
    return ast.unparse(ast.Module(body=nodes,type_ignores=[]))+"\n"


QUIZ_ONE_SAMPLES={
    "Even.py":"print(number % 2 == 0)\n",
    "Larger.py":"print(num_1 > num_2)\n",
    "Discount.py":"if is_member:\n    price *= 0.8\nprint(price)\n",
    "StringSums.py":"print(num_1 + num_2)\nprint(str(num_1) + str(num_2))\nprint(str(num_2) + str(num_1))\n",
    "OrderTotal.py":"shipping = 0 if subtotal >= 25 else 3 if subtotal >= 10 else 5\ntotal = subtotal + subtotal * tax_rate + shipping\nprint(\"Your total is ${0}.\".format(round(total, 2)))\n",
}


class Command(BaseCommand):
    help=__doc__

    def add_arguments(self,parser):
        parser.add_argument("--source",type=Path,default=Path("/course-var/vocareum-programming-quizzes"))
        parser.add_argument("--refresh",action="store_true",help="Create a new revision from the downloaded source.")

    @transaction.atomic
    def handle(self,*args,**options):
        source=options["source"]
        if not source.exists(): raise CommandError("Download and prepare the programming quiz archives first.")
        course=Course.objects.order_by("pk").first()
        if course is None: raise CommandError("Create or import the course first.")
        membership=Membership.objects.filter(course=course,role__in=["instructor","head_ta"]).select_related("user").first()
        user=membership.user if membership else get_user_model().objects.filter(is_superuser=True).first()
        if user is None: raise CommandError("An instructor account is required.")
        base_position=max([0,*course.lesson_set.values_list("position",flat=True)])+100
        imported=skipped=0
        for quiz_dir in sorted(source.glob("programming-quiz-*--*")):
            assignment_id=quiz_dir.name.rsplit("--",1)[-1]
            title=quiz_dir.name.rsplit("--",1)[0].replace("-"," ").title()
            number=int(re.search(r"\d+",title).group())
            lesson,_=Lesson.objects.get_or_create(course=course,source_path=f"vocareum:assignment:{assignment_id}",defaults={
                "title":f"Programming Quiz {number}","position":base_position+number,"visibility":"student",
                "metadata":{"kind":"programming_quiz","vocareum_assignment_id":assignment_id,"exam_mode":False,"time_limit_minutes":30},"deleted_at":None})
            for question_dir in sorted(quiz_dir.glob("question-*--*"),key=lambda p:int(p.name.split("-")[1])):
                part_id=question_dir.name.rsplit("--",1)[-1]
                position=int(question_dir.name.split("-")[1])
                definition_path=question_dir/"definition.json"
                if not definition_path.exists(): raise CommandError(f"Missing prepared definition for {question_dir.name}")
                ferb=(question_dir/"private"/"Ferb.py").read_text(errors="replace")
                expected_name=re.search(r'STUDENT_FILE_NAME\s*=\s*["\']([^"\']+)',ferb).group(1)
                raw_file=next(p for p in (question_dir/"startercode").iterdir() if p.is_file() and p.suffix==".py")
                raw_source=raw_file.read_text(errors="replace")
                student_source=scaffold(raw_source,raw_file.name)
                activity,created=Activity.objects.get_or_create(lesson=lesson,metadata__vocareum_part_id=part_id,defaults={
                    "title":f"Question {position} — {Path(expected_name).stem}","position":position,
                    "metadata":{"kind":"coding","category":"content","group":"Questions","quiz_question":True,"vocareum_part_id":part_id}})
                if not created and activity.revisions.exists() and not options["refresh"]: skipped+=1; continue
                revision=Revision.objects.create(activity=activity,number=(activity.revisions.order_by("-number").first().number+1 if activity.revisions.exists() else 1),created_by=user,
                    content={"version":1,"blocks":[{"id":"instructions","type":"coding","prompt":[{"type":"text","text":prompt_from_source(raw_source)}]}]},
                    grading={"maximum_points":"1","entrypoint":expected_name,"definition":json.loads(definition_path.read_text()),"source":"coursespace"})
                definition_text=json.dumps(json.loads(definition_path.read_text()),indent=2)+"\n"
                files=[(expected_name,"student",student_source),("full_results.txt","student",""),
                       ("grader/tests.json","grader",definition_text)]
                sample=question_dir/"private"/"sample_answer_1.py"
                sample_text=sample.read_text(errors="replace") if sample.exists() else QUIZ_ONE_SAMPLES.get(expected_name)
                if sample_text: files.append(("solutions/sample_answer.py","staff",sample_text))
                for path,visibility,text in files:
                    raw=text.encode();ActivityFile.objects.create(revision=revision,path=path,visibility=visibility,
                        blob=ContentFile(raw,name=Path(path).name),sha256=hashlib.sha256(raw).hexdigest())
                activity.published_revision=revision;activity.save(update_fields=["published_revision"]);imported+=1
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} programming quiz questions; kept {skipped} existing questions."))
