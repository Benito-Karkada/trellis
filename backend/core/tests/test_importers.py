from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

from django.test import SimpleTestCase

from core.importers.coding_archive import inspect_zip
from core.importers.edx import parse_problem_xml
from core.importers.kaltura import load_kaltura_catalog
from core.schema import validate_content

class EdxImporterTests(SimpleTestCase):
    def test_response_nested_question_and_code_are_preserved(self):
        raw = '''<problem><multiplechoiceresponse><pre>x = 1<br/>print(x)</pre><p>Read the code.</p><label>What prints?</label><choicegroup><choice correct="true">1<choicehint>PRIVATE_HINT</choicehint></choice><choice correct="false">2</choice></choicegroup></multiplechoiceresponse></problem>'''
        candidate = parse_problem_xml(raw)
        validate_content(candidate.content)
        prompt = candidate.content["blocks"][0]["prompt"]
        self.assertIn("What prints?", str(prompt))
        self.assertIn("Read the code.", str(prompt))
        self.assertIn("print(x)", str(prompt))
        self.assertIn("line_break", str(prompt))
        self.assertNotIn("PRIVATE_HINT", str(candidate.content))

    def test_separates_student_content_from_answers_and_preserves_code(self):
        raw = '''<problem display_name="Variables"><pre>print(1 + 2)</pre><label>What prints?</label><multiplechoiceresponse><choicegroup><choice correct="false">23<choicehint>Numeric addition.</choicehint></choice><choice correct="true"><pre>3</pre></choice></choicegroup></multiplechoiceresponse></problem>'''
        candidate = parse_problem_xml(raw)
        validate_content(candidate.content)
        question = candidate.content["blocks"][1]
        self.assertEqual(candidate.content["blocks"][0]["text"], "print(1 + 2)")
        self.assertNotIn("correct", str(candidate.content))
        self.assertNotIn("Numeric addition", str(candidate.content))
        self.assertEqual(candidate.grading["questions"][question["id"]]["correct_choice_ids"], [question["choices"][1]["id"]])

    def test_removes_export_line_marker_from_hint_but_preserves_python_newline(self):
        raw = r'''<problem><multiplechoiceresponse><choicegroup>
        <choice correct="true">GUI<choicehint>That is correct.\n</choicehint></choice>
        <choice correct="false">newline<choicehint>The value is "\n"</choicehint></choice>
        <choice correct="false">literal<choicehint>\n</choicehint></choice>
        </choicegroup></multiplechoiceresponse></problem>'''
        candidate = parse_problem_xml(raw)
        rules = next(iter(candidate.grading["questions"].values()))["choice_feedback"]
        values = [nodes[0]["text"] for nodes in rules.values()]
        self.assertEqual(values, ["That is correct.", 'The value is "\\n"', r"\n"])

    def test_multiple_native_question_types_and_solution(self):
        raw = '''<problem><label>Choose all</label><choiceresponse><checkboxgroup><choice correct="true"><font style="font-family:monospace">x</font></choice><choice correct="false">y</choice></checkboxgroup></choiceresponse><label>Name it</label><stringresponse answer="Python" type="ci"><additional_answer answer="python"/><textline size="20"/></stringresponse><solution><p>Because reasons.</p></solution></problem>'''
        candidate = parse_problem_xml(raw)
        validate_content(candidate.content)
        self.assertEqual([b["type"] for b in candidate.content["blocks"]], ["select_all", "fill_blank"])
        second = candidate.content["blocks"][1]
        self.assertEqual(candidate.grading["questions"][second["id"]]["answers"], ["Python", "python"])
        self.assertIn("solution", candidate.grading)

    def test_unsupported_elements_create_review_warnings(self):
        candidate = parse_problem_xml("<problem><customthing>Do not lose me</customthing></problem>")
        self.assertIn({"code": "unsupported_element", "tag": "customthing"}, candidate.warnings)
        self.assertEqual(candidate.raw_xml, "<problem><customthing>Do not lose me</customthing></problem>")

    def test_malformed_input_size_becomes_warning(self):
        candidate = parse_problem_xml('<problem><label>Answer</label><stringresponse answer="x"><textline size="Mayo"/></stringresponse></problem>')
        self.assertEqual(candidate.content["blocks"][0]["input"], {"size": 40})
        self.assertIn({"code": "invalid_input_size", "value": "Mayo"}, candidate.warnings)

    def test_nested_and_compound_option_inputs_are_not_lost(self):
        raw = '''<problem><pre>call()</pre><optionresponse><p>It should return</p><optioninput><option correct="True">True</option><option correct="False">False<optionhint>Try again</optionhint></option></optioninput><p>and currently returns</p><optioninput><option correct="False">True</option><option correct="True">False</option></optioninput></optionresponse></problem>'''
        candidate = parse_problem_xml(raw)
        validate_content(candidate.content)
        questions = [b for b in candidate.content["blocks"] if b["type"] == "multiple_choice"]
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["prompt"][0]["text"], "It should return")
        self.assertEqual(questions[1]["prompt"][0]["text"], "and currently returns")
        self.assertNotIn("Try again", str(candidate.content))

class KalturaTests(SimpleTestCase):
    def test_extracts_native_ids_from_course_csv_format(self):
        data = '''Video Name,Kaltura Embed URL\n1.1.1.0,"<iframe src='https://cdnapisec.kaltura.com/p/2019031/embedPlaykitJs/uiconf_id/45182411?entry_id=1_5zdafy32&config[provider]={""widgetId"":""1_zrxql1b2""}'></iframe>"\n'''
        videos, warnings = load_kaltura_catalog(data)
        self.assertEqual(warnings, [])
        self.assertEqual(videos["1.1.1.0"].entry_id, "1_5zdafy32")
        self.assertEqual(videos["1.1.1.0"].partner_id, "2019031")

class CodingArchiveTests(SimpleTestCase):
    def test_private_files_and_unknown_files_are_never_student_visible(self):
        with NamedTemporaryFile(suffix=".zip") as temp:
            with ZipFile(temp.name, "w") as archive:
                archive.writestr("Ferb.py", "grader")
                archive.writestr("sample_answer_1.py", "answer")
                archive.writestr("Exercise.py", "starter maybe")
                archive.writestr("../escape.py", "bad")
            files, warnings = inspect_zip(temp.name)
        self.assertEqual({f.path: f.visibility for f in files}, {"Ferb.py": "grader", "sample_answer_1.py": "staff", "Exercise.py": "quarantine"})
        self.assertIn({"code": "unsafe_path", "path": "../escape.py"}, warnings)
        self.assertIn({"code": "unclassified_files"}, warnings)
