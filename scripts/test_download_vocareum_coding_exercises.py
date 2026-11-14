import tempfile
from pathlib import Path
import stat
import unittest
from zipfile import ZipFile, ZipInfo

from download_vocareum_coding_exercises import (
    exercise_path,
    include_assignment,
    is_coding_part,
    safe_extract,
)


class SelectionTests(unittest.TestCase):
    def test_current_coding_titles_are_selected(self):
        self.assertTrue(is_coding_part("2.2.7 Coding Exercise 1"))
        self.assertTrue(is_coding_part("Coding Problem 2.2.8 (Advanced)"))
        self.assertFalse(is_coding_part("Exercise: bandicoot.py"))

    def test_out_of_scope_assignments_are_excluded(self):
        self.assertFalse(include_assignment("Unit 1 Test - Onboarding Exam"))
        self.assertFalse(include_assignment("TEST - Full Results Restore Experiment"))
        self.assertTrue(include_assignment("2.2 - Problem Set"))

    def test_paths_include_stable_ids(self):
        path = exercise_path(
            Path("archive"),
            {
                "assignment_id": "5591000",
                "assignment_name": "2.2 - Problem Set",
                "part_id": "5591043",
                "part_name": "Coding Problem 2.2.8 (Advanced)",
            },
        )
        self.assertEqual(
            path,
            Path("archive/exercises/2.2-problem-set--5591000/coding-problem-2.2.8-advanced--5591043"),
        )


class ExtractionTests(unittest.TestCase):
    def test_extracts_normal_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "files.zip"
            with ZipFile(archive, "w") as output:
                output.writestr("Ferb.py", "tests = []\n")
            self.assertEqual(safe_extract(archive, root / "private"), 1)
            self.assertEqual((root / "private/Ferb.py").read_text(), "tests = []\n")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "files.zip"
            with ZipFile(archive, "w") as output:
                output.writestr("../escape.py", "bad\n")
            with self.assertRaises(ValueError):
                safe_extract(archive, root / "private")
            self.assertFalse((root / "escape.py").exists())

    def test_omits_symlinks_but_keeps_regular_course_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "course.zip"
            link = ZipInfo("publicdata")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with ZipFile(archive, "w") as output:
                output.writestr("Utility.py", "helpers = True\n")
                output.writestr(link, "/somewhere/else")
            self.assertEqual(safe_extract(archive, root / "course"), 1)
            self.assertTrue((root / "course/Utility.py").exists())
            self.assertFalse((root / "course/publicdata").exists())


if __name__ == "__main__":
    unittest.main()
