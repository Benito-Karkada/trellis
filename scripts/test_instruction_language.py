import copy
import unittest
from refresh_coding_instruction_language import rewrite, update_nodes, prepare

class InstructionLanguageTests(unittest.TestCase):
    def test_editor_directions_preserve_task_and_line_constraints(self):
        text = "You may modify the lines of code above, but don't move them! Write some code below that will print the sum. Below are some lines of code that will test your function."
        changed = rewrite(text)
        self.assertNotIn('above', changed)
        self.assertNotIn('below', changed)
        self.assertIn("don't move them", changed)
        self.assertIn('print the sum', changed)
        self.assertEqual(rewrite(changed), changed)

    def test_mathematical_and_instructions_references_are_not_rewritten(self):
        text = 'Return True if temperature is below freezing. Use the formula above. Print "Ready or not, here I come!". The dealer hits below 17.'
        self.assertEqual(rewrite(text), text)

    def test_rich_code_and_attributes_are_preserved(self):
        nodes = [{'type':'element','tag':'p','children':[
            {'type':'text','text':'Complete the code below. '},
            {'type':'element','tag':'code','children':[{'type':'text','text':'"Write your code here!"'}]},
            {'type':'element','tag':'strong','children':[{'type':'text','text':'The variables above are inputs.'}]}]},
            {'type':'element','tag':'pre','children':[{'type':'text','text':'print("Below are some lines of code that will test your function.")'}]}]
        original = copy.deepcopy(nodes); changes = []; update_nodes(nodes, changes)
        self.assertEqual(nodes[1], original[1])
        self.assertEqual(nodes[0]['children'][1], original[0]['children'][1])
        self.assertEqual(nodes[0]['children'][2]['tag'], 'strong')
        self.assertIn('code editor', nodes[0]['children'][2]['children'][0]['text'])

    def test_content_only_plan_keeps_other_blocks_and_input_unchanged(self):
        part = {'id':1, 'title':'Example', 'assignment_id':2, 'revision_id':3,
                'published_revision_id':3, 'content':{'version':1,'blocks':[
                    {'id':'coding','type':'coding','prompt':[{'type':'text','text':'Write some code below that prints the sum.'}]},
                    {'id':'reading','type':'rich_text','body':[{'type':'text','text':'The example below explains the formula.'}]}]}}
        original = copy.deepcopy(part); row = prepare(part)
        self.assertEqual(part, original)
        self.assertEqual(row['content']['blocks'][1], original['content']['blocks'][1])
        self.assertEqual(row['files'], [])
        self.assertNotIn('grading', row)
        again = prepare({**part, 'content':row['content']})
        self.assertFalse(again['changes'])

if __name__ == '__main__': unittest.main()
