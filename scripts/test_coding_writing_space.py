import ast
import unittest
from add_coding_writing_space import writing_space, MARKER, prepare

class WritingSpaceTests(unittest.TestCase):
    def test_tests_get_space_and_keep_output_comments(self):
        source = '#These local tests should print 8.\nprint(double(4))\n'
        result = writing_space(source)
        self.assertTrue(result.startswith(MARKER + '\n'*5))
        self.assertIn(source, result)
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))
        self.assertEqual(writing_space(result), result)

    def test_input_defaults_stay_above_the_writing_area(self):
        source = 'x = 4\ny = 2\n\n\n\nprint(x+y)\n'
        result = writing_space(source)
        self.assertLess(result.index('y = 2'), result.index(MARKER))
        self.assertLess(result.index(MARKER), result.index('print('))

    def test_string_contents_and_continued_expressions_are_not_insertion_sites(self):
        for source in ['text = """a\n\n\n\nb"""\n', 'values = [1,\n\n\n\n2]\n']:
            result = writing_space(source)
            self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))
            self.assertTrue(result.endswith(MARKER + '\n'*5))

    def test_original_function_and_top_level_class_areas_recovered(self):
        original = 'def f():\n    x = 1\n    #Add some code here!\n\nprint(f())\n'
        current = 'def f():\n    x = 1\n\nprint(f())\n'
        self.assertIn('    '+MARKER, writing_space(current, original))
        original = 'class Helper:\n    x = 1\n#Add and modify your code here!\nprint(NewClass())\n'
        current = 'class Helper:\n    x = 1\n\nprint(NewClass())\n'
        result = writing_space(current, original)
        self.assertIn('\n'+MARKER+'\n', result)
        self.assertEqual(ast.dump(ast.parse(current)), ast.dump(ast.parse(result)))
        self.assertEqual(writing_space(result, original), result)

    def test_multiple_original_edit_areas_are_preserved(self):
        original = 'x = 1\n#Add your lines of code here!\nx += 2\n#Add your lines of code here!\n'
        current = 'x = 1\n\nx += 2\n'
        result = writing_space(current, original)
        self.assertEqual(result.count(MARKER), 2)
        self.assertEqual(writing_space(result, original), result)

    def test_deliberate_syntax_error_stays_broken(self):
        source = 'value = (1 + 2\nprint(value)\n'
        self.assertEqual(writing_space(source).split(MARKER)[0].strip(), source.strip())
        with self.assertRaises(SyntaxError):
            ast.parse(writing_space(source))

    def test_repeatable_with_short_existing_gap_and_unclosed_expression(self):
        for source in ['x = 1\n\n\nprint(x)\n', 'def f():\n    return 1\n\nprint(f())\n', 'x = (1 + 2\n\nprint(x)\n']:
            result = writing_space(source)
            self.assertEqual(writing_space(result), result)
        self.assertNotIn('    '+MARKER, writing_space('def f():\n    return 1\n\nprint(f())\n'))

    def test_unclosed_multiline_string_is_preserved_for_review(self):
        with self.assertRaisesRegex(ValueError, 'Unclosed multiline string'):
            writing_space('text = """hello\n')

    def test_sandbox_and_unpublished_draft_excluded(self):
        p = {'id':1, 'assignment_id':1, 'title':'Example', 'kind':'coding', 'metadata':{'sandbox':True}, 'revision_id':1, 'published_revision_id':1}
        self.assertEqual(prepare({'part':p})['status'], 'excluded')
        p['metadata'] = {};p['published_revision_id'] = 0
        self.assertEqual(prepare({'part':p})['status'], 'review')

if __name__ == '__main__': unittest.main()
