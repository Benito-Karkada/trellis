import tempfile, unittest
from pathlib import Path
from zipfile import ZipFile, ZipInfo
from restore_sandbox_starters import archive_files, normalized

class SandboxArchiveTests(unittest.TestCase):
    def read(self, entries):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'startercode.zip'
            with ZipFile(archive,'w') as z:
                for name,raw in entries:z.writestr(name,raw)
            return archive_files(archive)
    def test_preserves_comments_errors_and_supporting_files_verbatim(self):
        source=b'# Try fixing this example!\r\nprint(missing_name)\r\n'
        self.assertEqual(self.read([('Example.py',source),('data.txt',b'hello\n')]),{'Example.py':source,'data.txt':b'hello\n'})
    def test_supports_wrapped_export(self):
        self.assertEqual(self.read([('voc/startercode/Example.py',b'# hello')]),{'Example.py':b'# hello'})
    def test_rejects_traversal_absolute_and_backslash(self):
        for name in ['../secret.py','/secret.py','folder/../../secret.py','folder\\secret.py']:
            with self.subTest(name=name),self.assertRaises(ValueError):self.read([(name,b'')])
    def test_rejects_symlink(self):
        item=ZipInfo('example.py');item.create_system=3;item.external_attr=0o120777<<16
        with self.assertRaises(ValueError):self.read([(item,b'/etc/passwd')])
    def test_rejects_private_grading_files(self):
        for name in ['private/test.py','Ferb.py','phineas_v2.py']:
            with self.subTest(name=name),self.assertRaises(ValueError):self.read([(name,b'')])
    def test_rejects_duplicate_normalized_path(self):
        with self.assertRaises(ValueError):self.read([('Example.py',b''),('startercode/Example.py',b'')])
    def test_rejects_empty_archive(self):
        with self.assertRaises(ValueError):self.read([])
    def test_title_matching_keeps_part_numbers(self):
        self.assertEqual(normalized('4.4.3: Writing Files, Part 1 of 2 Sandbox'),normalized('4.4.3 Writing Files Part 1 of 2 Sandbox'))
        self.assertNotEqual(normalized('Part 1 of 2'),normalized('Part 2 of 2'))
if __name__=='__main__':unittest.main()
