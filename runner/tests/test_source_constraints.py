import unittest
from grading import Case,Exercise,Observation,Requirement,grade
class Executor:
 def run(self,request):return Observation('ok',5)
class SourceConstraintTests(unittest.TestCase):
 def check(self,source,kind,target,variables=None):
  return grade(source,Exercise((Case('v','Value',5,target='answer',variables=variables or {}),),requirements=(Requirement('r',kind,target,'Required learning constraint.'),)),Executor())['passed']
 def test_tokens_ignore_comments_and_accept_quotes_and_whitespace(self):
  self.assertTrue(self.check("answer=5\nprint ( 'hello' )",'require_source','print("hello")'))
  self.assertFalse(self.check('answer=5\n# print("hello")','require_source','print("hello")'))
  self.assertTrue(self.check('answer=5\nprint("type(")','forbid_source','type('))
 def test_incomplete_fragments_do_not_raise_and_identifiers_are_not_substrings(self):
  self.assertTrue(self.check('answer=5\nf.close()','require_source','close('))
  self.assertTrue(self.check('answer=5\ndifferent=1','forbid_source','if'))
 def test_comment_requirements_cannot_be_satisfied_with_strings(self):
  self.assertTrue(self.check('answer=5\n# Prints the number 1','require_comment','#Prints the number 1'))
  self.assertFalse(self.check('answer=5\ns="#Prints the number 1"','require_comment','#Prints the number 1'))
 def test_literals_are_type_sensitive_and_input_declarations_are_excluded(self):
  self.assertTrue(self.check('given=True\nanswer=5','forbid_constant','true',{'given':False}))
  self.assertFalse(self.check('given=True\nanswer=True','forbid_constant','true',{'given':False}))
  self.assertTrue(self.check('answer=5','forbid_constant','true'))

 def test_nested_conditionals_and_no_and_operator(self):
  starter='sunny=True\nwindy=False\nif sunny and not windy:\n print("Wear a hat!")\nif sunny and windy:\n print("Enjoy the breeze!")'
  nested='sunny=True\nwindy=False\nif sunny:\n if windy:\n  print("Enjoy the breeze!")\n else:\n  print("Wear a hat!")'
  self.assertFalse(self.check(starter,'forbid_node','And'))
  self.assertFalse(self.check(starter,'require_nested_if','If'))
  self.assertTrue(self.check(nested,'forbid_node','And'))
  self.assertTrue(self.check(nested,'require_nested_if','If'))
  self.assertFalse(self.check('if True:\n pass\nelif False:\n pass','require_nested_if','If'))
  self.assertFalse(self.check('text="if sunny: if windy:" # and','require_nested_if','If'))
  self.assertTrue(self.check('if False:\n pass\nelse:\n if True:\n  pass','require_nested_if','If'))
  self.assertTrue(self.check(nested+'\n# and is not allowed\ntext="sand and sun"','forbid_node','And'))
