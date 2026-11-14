import ast,unittest
from clean_coding_instructions import clean_source,prepare,plain

class CleanupTests(unittest.TestCase):
 def test_strings_inputs_and_print_calls_are_unchanged(self):
  source='# Instructions\nx = 5\ns = "# keep"\ntext = """a\n\n\n\nb"""\n# More instructions\nprint(x, s, text)\n'
  cleaned,_,count=clean_source(source)
  self.assertEqual(count,2);self.assertEqual(ast.dump(ast.parse(source)),ast.dump(ast.parse(cleaned)));self.assertIn('\n\n\n\nb',cleaned)
 def test_required_comments_survive(self):
  cleaned,_,_=clean_source('# Instructions\n#Prints the number 1\nprint(1)\n',['#Prints the number 1'])
  self.assertIn('#Prints the number 1',cleaned);self.assertNotIn('# Instructions',cleaned)
 def test_intentional_syntax_errors_are_not_fixed(self):
  cleaned,_,_=clean_source('# Fix the parentheses\nx = (1 + 2\nprint(x)\n')
  self.assertEqual(cleaned,'x = (1 + 2\nprint(x)\n')
  with self.assertRaises(SyntaxError):ast.parse(cleaned)
 def test_original_xml_only_information_is_preserved(self):
  part={'id':1,'assignment_id':2,'title':'Example','revision_id':3,'grading':{},'content':{'version':1,'blocks':[{'id':'instructions','type':'coding','prompt':[{'type':'text','text':'Extra XML details. First paragraph. Second paragraph.'}]}]}}
  result=prepare({'part':part,'files':{'main.py':'#First paragraph.\n#\n#Second paragraph.\nprint(1)\n'}})
  text=' '.join(plain(result['content']['blocks'][0]['prompt']).split())
  self.assertIn('Extra XML details.',text);self.assertIn('First paragraph.',text);self.assertIn('Second paragraph.',text)
  self.assertGreaterEqual(len(result['content']['blocks'][0]['prompt']),2)
 def test_comment_characters_in_strings_are_not_instruction_comments(self):
  cleaned,_,_=clean_source('value = """\n# This is a string\n"""\nprint(value)\n')
  self.assertIn('# This is a string',cleaned)

 def test_local_tests_expected_output_and_commented_prints_survive(self):
  source='#Describe the function.\n#Add your code here!\n\n#Below are some lines of code that will test your function.\n#If your function works correctly, this should print 8.\n#print(double(4))\nprint(double(4))\n'
  cleaned,comments,_=clean_source(source)
  self.assertIn('#If your function works correctly, this should print 8.',cleaned)
  self.assertIn('#print(double(4))',cleaned);self.assertIn('print(double(4))',cleaned)
  self.assertNotIn('Add your code here',cleaned);self.assertNotIn('this should print 8',' '.join(comments))
 def test_duplicate_prose_and_placeholder_cues_removed_but_real_instructions_kept(self):
  from core.coding_content import clean_prompt
  nodes=[{'type':'element','tag':'p','children':[{'type':'text','text':'Use x == 1. Use x != 1. Add your code here!'}]},
   {'type':'element','tag':'h3','children':[{'type':'text','text':'Workspace instructions'}]},
   {'type':'element','tag':'p','children':[{'type':'text','text':'Use x == 1. Keep the value assignments.'}]}]
  result=plain(clean_prompt(nodes))
  self.assertEqual(result.count('Use x == 1.'),1);self.assertIn('Use x != 1.',result);self.assertIn('Keep the value assignments.',result)
  self.assertNotIn('Add your code here',result);self.assertNotIn('Workspace instructions',result)
 def test_meaningful_below_instruction_is_not_removed(self):
  from core.coding_content import clean_prompt
  result=plain(clean_prompt([{'type':'text','text':'Add your code below to compute the total.'}]))
  self.assertIn('Add your code below to compute the total.',result)
 def test_rich_inline_fragments_and_code_are_not_deduplicated(self):
  from core.coding_content import clean_prompt
  nodes=[{'type':'element','tag':'p','children':[{'type':'text','text':'Use '},{'type':'element','tag':'code','children':[{'type':'text','text':'x + x'}]},{'type':'text','text':' with '},{'type':'element','tag':'strong','children':[{'type':'text','text':'x'}]},{'type':'text','text':' with y.'}]}]
  self.assertEqual(clean_prompt(nodes),nodes)
 def test_bullet_conditions_stay_separate_list_items(self):
  from core.coding_content import clean_prompt
  nodes=clean_prompt([{'type':'text','text':'Choose: - If x > 0, print positive. - If x == 0, print zero. - Otherwise, print negative.'}])
  self.assertEqual(nodes[1]['tag'],'ul');self.assertEqual(len(nodes[1]['children']),3)

 def test_list_prefix_deduplication_is_idempotent(self):
  from core.coding_content import clean_prompt
  nodes=[{'type':'text','text':'Choose an option: - If x, do A. - If y, do B. - Otherwise, do C.'},
    {'type':'text','text':"You may edit the inputs! Choose an option:"}]
  result=clean_prompt(nodes)
  self.assertEqual(clean_prompt(result),result)
  self.assertEqual(plain(result).count('Choose an option:'),1)

if __name__=='__main__':unittest.main()
