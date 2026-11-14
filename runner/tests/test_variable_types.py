import os
import unittest
from grading import Case, Exercise, Observation, RunRequest, grade
from grading.docker_executor import DockerExecutor
from grading.manifest import load_definition


def exercise():
    types = [("my_integer", "int"), ("my_decimal", "float"), ("my_string", "str"), ("my_boolean", "bool")]
    return Exercise(tuple(Case(name, name, kind, action="variable_type", target=name) for name, kind in types) +
                    (Case("output", "Output", "<class 'int'>\n<class 'float'>\n<class 'str'>\n<class 'bool'>",
                          action="stdout", strip_output=True),))


class TypeDefinitionTests(unittest.TestCase):
    def test_normalization_is_opt_in_and_type_expectations_are_validated(self):
        class Fake:
            def run(self, _):return Observation("ok", stdout="hello\n")
        self.assertFalse(grade("pass", Exercise((Case("o", "Output", "hello", action="stdout"),)), Fake())["passed"])
        self.assertTrue(grade("pass", Exercise((Case("o", "Output", "hello", action="stdout", strip_output=True),)), Fake())["passed"])
        for expected in ([], 1, "custom"):
            with self.assertRaises(ValueError):
                Exercise((Case("v", "Type", expected, action="variable_type", target="x"),)).validate()

    def test_native_type_manifest_loads(self):
        self.assertEqual(load_definition({"version":1,"cases":[{
            "id":"type", "label":"Type", "expected":"int", "action":"variable_type", "target":"x"}]}).cases[0].action,"variable_type")



@unittest.skipUnless(os.environ.get("RUN_DOCKER_TESTS")=="1", "Opt-in Docker integration")
class RealTypeTests(unittest.TestCase):
    def test_accepts_different_values_and_checks_all_variables_and_output(self):
        source="my_integer=-27\nmy_decimal=0.0\nmy_string=''\nmy_boolean=False\nfor value in (my_integer,my_decimal,my_string,my_boolean): print(type(value))"
        result=grade(source, exercise(), DockerExecutor(), operation="submit")
        self.assertTrue(result["passed"])
        self.assertIn("of type bool, and it was",result["full_output"])
        for broken in (source.replace("my_integer=-27", "my_integer=True"),
                       source.replace("my_decimal=0.0", "my_decimal=0"),
                       source.replace("print(type(value))", "print('wrong')")):
            self.assertFalse(grade(broken, exercise(), DockerExecutor())["passed"])

    def test_missing_variables_and_custom_class_names_do_not_pass(self):
        result=grade("pass",exercise(),DockerExecutor())
        self.assertIn("variable called my_integer, but we did not",result["full_output"])
        result=grade("class int: pass\nx=int()",Exercise((Case("x","Type","int",action="variable_type",target="x"),)),DockerExecutor())
        self.assertFalse(result["passed"])
