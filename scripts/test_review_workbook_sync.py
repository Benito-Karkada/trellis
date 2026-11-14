import unittest
from unittest.mock import Mock
from sync_review_workbook import sync,column,validate

class WorkbookSafetyTests(unittest.TestCase):
 def data(self):
  return {'schema_version':2,'course_id':1,'columns':['Enrollment ID','GTID','Name','Sus index / 100','Timing metric','Code metric','First-pass metric','Focus metric']+['Metric']*24,
   'rows':[['1','001234567','Test',None]+[None]*28],'formulas':[{}],'methodology':'Private review aid','weights':{'timing':35,'code':35,'first_pass':20,'focus':10}}
 def test_columns_and_validation(self):
  self.assertEqual(column(33),'AG');self.assertEqual(validate(self.data(),1)['rows'][0][1],'001234567')
  d=self.data();d['rows'][0][2]='=CMD()'
  with self.assertRaises(ValueError):validate(d,1)
  with self.assertRaises(ValueError):validate(self.data(),2)
 def test_wrong_destination_never_receives_a_token(self):
  g=Mock()
  with self.assertRaises(ValueError):sync(g,self.data(),'https://example.test/book.xlsx',True)
  g.call.assert_not_called()
 def test_dry_run_only_reads(self):
  g=Mock();g.call.side_effect=[{'name':'scores.xlsx','id':'book','parentReference':{'driveId':'drive'}},{'value':[]}]
  sync(g,self.data(),'https://gtvault-my.sharepoint.com/:x:/g/example')
  self.assertTrue(all(c.args[0]=='GET' for c in g.call.call_args_list))
 def test_existing_unowned_sheet_cannot_be_overwritten(self):
  g=Mock();g.call.side_effect=[{'name':'scores.xlsx','id':'book','parentReference':{'driveId':'drive'}},
    {'value':[{'name':'Trellis Review 1','id':'sheet'}]},{'values':[['unrelated content']]}]
  with self.assertRaises(ValueError):sync(g,self.data(),'https://gtvault-my.sharepoint.com/:x:/g/example',True)
  self.assertTrue(all(c.args[0]=='GET' for c in g.call.call_args_list))
 def test_owned_legacy_sheet_is_migrated_and_formulas_use_shared_weights(self):
  d=self.data();legacy=d['columns'][:];legacy.insert(4,'Formula')
  g=Mock();g.s.headers={}
  g.call.side_effect=[
   {'name':'scores.xlsx','id':'book','parentReference':{'driveId':'drive'}},
   {'value':[{'name':'Trellis Review 1','id':'sheet'}]},
   {'values':[['Trellis review schema 1; course 1']]}, {'values':[legacy]}, {'values':[[2]]},
   {'id':'session'}, {}, {}, {}, {}, {}, {}, {}, {},
   {'values':[d['columns'],['1','001234567','Test','']+[None]*28]}, {}, {}]
  sync(g,d,'https://gtvault-my.sharepoint.com/:x:/g/example',True)
  calls=g.call.call_args_list
  formulas=next(c.args[2]['formulas'] for c in calls if len(c.args)>2 and 'formulas' in c.args[2])
  self.assertEqual(formulas[0][3],'=IF(COUNT(E2:H2)=0,"",ROUND(SUMPRODUCT(E2:H2,$AJ$2:$AM$2),1))')
  self.assertEqual(formulas[0][8],'=IF(ISNUMBER(E2),E2*$AJ$2,"")')
  self.assertTrue(any("AG1:AG3" in c.args[1] for c in calls))
  self.assertTrue(any(c.args[0]=='POST' and c.args[1].endswith('/closeSession') for c in calls))
if __name__=='__main__':unittest.main()
