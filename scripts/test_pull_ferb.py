import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from pull_ferb import cached_parts, cached_ferb, zip_ferb, remote_parts, run
from download_vocareum_coding_exercises import VocareumClient


class FerbSourceTests(unittest.TestCase):
    def test_assignment_discovery_does_not_stop_at_short_first_page(self):
        client=VocareumClient('test')
        client.json=Mock(side_effect=[{'assignments':[{'id':str(i)} for i in range(10)]},
                                     {'assignments':[{'id':'later'}]}, {'assignments':[]}, {'assignments':[]}])
        self.assertEqual(len(client.assignments('144164')),11)
        self.assertEqual(client.json.call_args_list[1].args[1]['page'],2)

    def test_parts_are_fetched_for_every_discovered_assignment(self):
        client=Mock()
        client.assignments.return_value=[{'id':'a','parts':['incomplete']},{'id':'b'}]
        client.parts.side_effect=[[{'id':'100'}],[{'id':'200'}]]
        self.assertEqual(set(remote_parts(client,'144164')),{'100','200'})
        self.assertEqual(client.parts.call_count,2)

    def test_local_archives_match_course_and_preserve_case_insensitive_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'exercises/assignment/part';(folder/'private').mkdir(parents=True)
            (folder/'manifest.json').write_text(json.dumps({'course_id':'144164','part_id':'123','assignment_id':'456'}))
            (folder/'private/Ferb.py').write_text('# Do not execute\n')
            self.assertEqual(list(cached_parts(root,'144164')),['123'])
            self.assertEqual(cached_parts(root,'other'),{})
            self.assertEqual(cached_ferb(folder),('private/Ferb.py',b'# Do not execute\n'))

    def test_zip_uses_only_ferb_and_rejects_ambiguous_or_traversal_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'private.zip'
            with ZipFile(path,'w') as archive:
                archive.writestr('nested/FerB.PY','a = 1\n');archive.writestr('other.py','must not be copied')
            self.assertEqual(zip_ferb(path),('nested/FerB.PY',b'a = 1\n'))
            with ZipFile(path,'w') as archive:
                archive.writestr('Ferb.py','a');archive.writestr('nested/ferb.py','b')
            with self.assertRaisesRegex(ValueError,'Multiple different'):zip_ferb(path)
            with ZipFile(path,'w') as archive:archive.writestr('../Ferb.py','a')
            with self.assertRaisesRegex(ValueError,'Unsafe'):zip_ferb(path)

    def test_cached_collection_needs_no_token_or_network_and_reports_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=root/'cache';folder=cache/'exercises/assignment/part';(folder/'private').mkdir(parents=True)
            (folder/'manifest.json').write_text(json.dumps({'course_id':'144164','part_id':'123','assignment_id':'456'}))
            (folder/'private/Ferb.py').write_text('# Original source\n')
            report=root/'report.json';report.write_text(json.dumps([{'part_id':89,'assignment_id':3,'title':'Exercise','vocareum_part_id':'123'},
                                                                   {'part_id':90,'title':'Unmapped','vocareum_part_id':None}]))
            args=argparse.Namespace(report=report,out=root/'out',course='144164',archive_root=cache,token_file=root/'does-not-exist',refresh=False,limit=None)
            with patch('pull_ferb.VocareumClient') as client,redirect_stdout(io.StringIO()):
                self.assertEqual(run(args),0);client.assert_not_called()
            manifest=json.loads((args.out/'manifest.json').read_text());self.assertEqual(manifest['summary'],{'saved':1,'unmapped':1,'error':0})
            self.assertEqual((args.out/'part-89--Exercise/Ferb.py').read_text(),'# Original source\n')
            # A rerun must not overwrite a source someone has edited by hand.
            (args.out/'part-89--Exercise/Ferb.py').write_text('# Edited\n')
            with redirect_stdout(io.StringIO()):self.assertEqual(run(args),1)
            self.assertEqual((args.out/'part-89--Exercise/Ferb.py').read_text(),'# Edited\n')


if __name__=='__main__':unittest.main()
