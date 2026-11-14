"""Create self-contained local teaching examples; preserve edits on subsequent runs."""
import hashlib
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Activity, ActivityFile, Course, Lesson, Membership, Revision
from core.schema import validate_content
from core.workspace_files import RESULTS_PLACEHOLDER


def text(value):
    return [{"type": "text", "text": value}]


def paragraph(key, value):
    return {"id": key, "type": "paragraph", "content": text(value)}


class Command(BaseCommand):
    help = "Seed a local CS 1301 demo with lessons, questions, coding practice and a quiz."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("The demo is available only with DEBUG=1.")
        users = get_user_model()
        instructor, created = users.objects.get_or_create(username="studio-instructor", defaults={
            "email": "instructor@trellis.local", "first_name": "Demo", "last_name": "Instructor"})
        if created:
            instructor.set_password("trellis-demo-2026")
            instructor.save()
        student, created = users.objects.get_or_create(username="student@trellis.local", defaults={
            "email": "student@trellis.local", "first_name": "Demo", "last_name": "Student"})
        if created:
            student.set_password("trellis-demo-2026")
            student.save()
        course, _ = Course.objects.get_or_create(term="Local demo", defaults={
            "title": "Introduction to Computing", "metadata": {"local_demo": True}})
        Membership.objects.get_or_create(user=instructor, course=course, defaults={"role": "instructor"})
        Membership.objects.get_or_create(user=student, course=course, defaults={"role": "student"})

        def lesson(key, title, position, metadata=None, visibility="student"):
            item, _ = Lesson.objects.get_or_create(course=course, metadata__demo_key=key, defaults={
                "title": title, "position": position, "visibility": visibility,
                "metadata": {"demo_key": key, **(metadata or {})}})
            return item

        def part(parent, key, title, position, blocks, grading=None, files=None, **metadata):
            item, _ = Activity.objects.get_or_create(lesson=parent, metadata__demo_key=key, defaults={
                "title": title, "position": position, "metadata": {"demo_key": key, **metadata}})
            if item.revisions.exists():
                return item
            content = {"version": 1, "blocks": blocks}
            validate_content(content)
            revision = Revision.objects.create(activity=item, number=1, content=content,
                                                grading=grading or {}, created_by=instructor)
            for name, (visibility, value) in (files or {}).items():
                data = value.encode()
                ActivityFile.objects.create(revision=revision, path=name, visibility=visibility,
                    sha256=hashlib.sha256(data).hexdigest(), blob=ContentFile(data, name=name.rsplit("/", 1)[-1]))
            item.published_revision = revision
            item.save(update_fields=["published_revision"])
            return item

        variables = lesson("variables", "Chapter 1.1 · Variables and expressions", 0)
        part(variables, "welcome", "Variables and values", 0, [
            paragraph("intro", "A variable gives a value a name. Use the name to refer to that value later in your program."),
            {"id": "example", "type": "code", "language": "python", "text": "students = 12\nstudents = students + 3\nprint(students)"},
            paragraph("explanation", "The second assignment uses the previous value of students and stores the result. The program prints 15.")
        ], kind="reading", category="content")
        part(variables, "variable-question", "Check your understanding", 1, [
            {"id": "q1", "type": "multiple_choice", "prompt": text("What does the example print?"), "choices": [
                {"id": "a", "content": text("12")}, {"id": "b", "content": text("15")}, {"id": "c", "content": text("students")}]}
        ], {"maximum_points": "1", "questions": {"q1": {"selection": "one", "correct_choice_ids": ["b"],
            "choice_feedback": {"a": text("The second assignment changes the value before it is printed."),
                                "b": text("The value starts at 12, then increases by 3."),
                                "c": text("Python prints the stored value when the name is not inside quotes.")}}}},
             kind="question", category="content")
        part(variables, "sandbox", "Experiment with variables", 2, [
            {"id": "sandbox", "type": "coding", "prompt": text("Change the values and run the program. This workspace is ungraded.")}
        ], {"entrypoint": "main.py", "maximum_points": "0"}, {
            "main.py": ("student", '# Try changing the values or adding another variable.\nname = "Trellis"\ncount = 3\n\nprint(name)\nprint(count + 2)\n')
        }, kind="coding", category="content", sandbox=True)
        cases = [{"id": f"sum-{i}", "label": label, "action": "stdout", "public": True,
                  "variables": {"a": a, "b": b}, "expected": str(a + b) + "\n"}
                 for i, (a, b, label) in enumerate([(7, 3, "Positive values"), (-4, 7, "Negative value"), (0, 0, "Zero")], 1)]
        definition = {"version": 1, "scoring": "all_or_nothing", "cases": cases}
        part(variables, "sum", "Coding exercise · Add two values", 3, [
            {"id": "sum", "type": "coding", "prompt": text("Print the sum of a and b. Keep the two assignments at the start of main.py; submission tests will use different values.")}
        ], {"entrypoint": "main.py", "maximum_points": "3", "definition": definition}, {
            "main.py": ("student", "a = 7\nb = 3\n\n# Add your code here.\n\n\n\n# With the values above, your program should print 10.\n"),
            "full_results.txt": ("student", RESULTS_PLACEHOLDER), "sample_answer.py": ("student", ""),
            "solutions/sample_answer.py": ("staff", "a = 7\nb = 3\nprint(a + b)\n"),
            "grader/tests.json": ("grader", json.dumps(definition, indent=2) + "\n")
        }, kind="coding", category="problem_set")

        functions = lesson("functions", "Chapter 1.2 · Functions", 1)
        part(functions, "functions-intro", "Returning a value", 0, [
            paragraph("intro", "A function can return a value to its caller. The caller can print that value or use it in another expression."),
            {"id": "code", "type": "code", "language": "python", "text": "def double(value):\n    return value * 2\n\nprint(double(4))"}
        ], kind="reading", category="content")

        def function_exercise(parent, key, title, position, name, argument, expected, answer, quiz=False):
            definition = {"version": 1, "scoring": "all_or_nothing", "cases": [
                {"id": f"case-{i}", "label": f"Example {i}", "action": "function", "target": name,
                 "arguments": [value], "expected": result, "public": True}
                for i, (value, result) in enumerate(zip(argument, expected), 1)]}
            starter = f"def {name}(value):\n    # Add your code here.\n    pass\n\n\n# This should print {expected[0]}.\nprint({name}({argument[0]!r}))\n"
            files = {"main.py": ("student", starter), "full_results.txt": ("student", RESULTS_PLACEHOLDER),
                     "solutions/sample_answer.py": ("staff", f"def {name}(value):\n    return {answer}\n"),
                     "grader/tests.json": ("grader", json.dumps(definition, indent=2) + "\n")}
            if not quiz:
                files["sample_answer.py"] = ("student", "")
            return part(parent, key, title, position, [{"id": key, "type": "coding", "prompt": text(
                f"Implement {name}(value). {title}. Return the result from the function.")}],
                {"entrypoint": "main.py", "maximum_points": "2", "definition": definition}, files,
                kind="coding", category="content" if quiz else "problem_set", quiz_question=quiz)

        function_exercise(functions, "double", "Multiply the value by two", 1, "double", [4, -3, 0], [8, -6, 0], "value * 2")
        quiz = lesson("quiz", "Programming Quiz · Functions", 2,
                      {"kind": "programming_quiz", "exam_mode": False, "time_limit_minutes": 20, "unit_number": 1}, "staff")
        for index, (name, argument, expected, answer, title) in enumerate([
            ("double", [2, -1, 0], [4, -2, 0], "value * 2", "Multiply the value by two"),
            ("square", [2, -3, 0], [4, 9, 0], "value * value", "Square the value"),
            ("increment", [2, -1, 0], [3, 0, 1], "value + 1", "Increase the value by one"),
            ("positive", [2, -1, 0], [True, False, False], "value > 0", "Return whether the value is positive"),
            ("magnitude", [2, -3, 0], [2, 3, 0], "abs(value)", "Return the absolute value")
        ], 1):
            function_exercise(quiz, f"quiz-{index}", f"Question {index} · {title}", index - 1,
                              name, argument, expected, answer, quiz=True)
        self.stdout.write(self.style.SUCCESS("Local demo ready. Existing course edits and passwords were preserved."))
