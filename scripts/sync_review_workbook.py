#!/usr/bin/env python3
"""Refresh only Trellis's owned worksheet in the specified SharePoint workbook.

Dry-run by default. Set TRELLIS_URL, TRELLIS_API_TOKEN, MS_GRAPH_ACCESS_TOKEN.
Microsoft token must be delegated work/school Files.ReadWrite (not app-only).
Never prints credentials, student rows, or Microsoft error bodies.
"""
import argparse
import base64
import json
import os
from pathlib import Path
from urllib.parse import quote,urlsplit
import requests
from api_client import Trellis

DEFAULT_WORKBOOK='https://gtvault-my.sharepoint.com/:x:/g/personal/bkarkada3_gatech_edu/IQCvk57--lADRr6vXNrwx_dEASF6plpN0-mZwl7rqfE5qns?e=dLQsc6'


def column(n):
    value=''
    while n:n,r=divmod(n-1,26);value=chr(65+r)+value
    return value


def validate(data,course):
    if data.get('schema_version')!=2 or data.get('course_id')!=course:raise ValueError('Wrong export schema/course.')
    cols=data['columns'];rows=data['rows'];forms=data['formulas']
    if len(cols)!=32 or len(rows)>10000 or len(rows)!=len(forms):raise ValueError('Invalid worksheet dimensions.')
    if cols[:8]!=['Enrollment ID','GTID','Name','Sus index / 100','Timing metric','Code metric','First-pass metric','Focus metric']:raise ValueError('Unexpected worksheet headers.')
    if len({r[0] for r in rows})!=len(rows) or any(len(r)!=len(cols) for r in rows):raise ValueError('Duplicate students or invalid rows.')
    # Reconstruct trusted formulas locally rather than trusting formulas from a URL.
    allowed={'timing':35,'code':35,'first_pass':20,'focus':10}
    if data['weights']!=allowed:raise ValueError('Review weights changed; update this client before syncing.')
    for row in rows:
        for cell in row:
            if isinstance(cell,str) and (cell.lstrip().startswith(('=','+','-','@')) or cell.startswith(('\t','\r','\n'))):
                raise ValueError('Unescaped worksheet text.')
    return data


class Graph:
    def __init__(self,token):
        if not token:raise ValueError('Set MS_GRAPH_ACCESS_TOKEN to a delegated Files.ReadWrite token. Do not paste tokens into chat.')
        self.s=requests.Session();self.s.trust_env=False;self.s.headers['Authorization']='Bearer '+token
    def call(self,method,path,body=None):
        if not path.startswith('/') or path.startswith('//'):raise ValueError('Graph paths must remain relative.')
        r=self.s.request(method,'https://graph.microsoft.com/v1.0'+path,json=body,timeout=90,allow_redirects=False)
        if not r.ok:
            raise RuntimeError(f'Microsoft Graph returned HTTP {r.status_code}. Check delegated permission, workbook access, or concurrent edits. No student data is logged.')
        return r.json() if r.content else {}


def sync(graph,data,link,apply=False):
    parsed=urlsplit(link)
    if parsed.scheme!='https' or parsed.hostname!='gtvault-my.sharepoint.com' or not parsed.path.startswith('/:x:/'):
        raise ValueError('Expected the GT SharePoint Excel sharing link.')
    encoded='u!'+base64.urlsafe_b64encode(link.encode()).decode().rstrip('=')
    item=graph.call('GET','/shares/'+encoded+'/driveItem')
    if not item.get('name','').lower().endswith('.xlsx'):raise ValueError('Destination is not an Excel workbook.')
    root='/drives/'+quote(item['parentReference']['driveId'],safe='')+'/items/'+quote(item['id'],safe='')+'/workbook'
    sheets=graph.call('GET',root+'/worksheets')['value'];name=f'Trellis Review {data["course_id"]}'
    sheet=next((s for s in sheets if s['name']==name),None);marker=f'Trellis review schema 2; course {data["course_id"]}'
    if sheet:
        sid=quote(sheet['id'],safe='');base=root+'/worksheets/'+sid
        previous=graph.call('GET',base+"/range(address='AI1')").get('values')
        legacy=previous==[[f'Trellis review schema 1; course {data["course_id"]}']]
        if previous!=[[marker]] and not legacy:
            raise ValueError('Existing worksheet has no ownership marker. Refusing to overwrite it.')
        expected=list(data['columns'])
        if legacy:expected.insert(4,'Formula')
        headers=graph.call('GET',base+f"/range(address='A1:{column(len(expected))}1')").get('values')
        # A previous interrupted migration may already have written the new headers.
        if headers!=[expected] and not (legacy and headers==[data['columns']+['']]):
            raise ValueError('Existing worksheet headers changed. Refusing to overwrite it.')
        old=graph.call('GET',base+"/range(address='AI2')").get('values',[[0]])[0][0]
        if type(old) not in {int,float} or not 0<=old<=10000:raise ValueError('Invalid previous row count.')
        old=int(old)
    else:old=0;legacy=False
    print(f'Destination: {item["name"]}; worksheet: {name}; {len(data["rows"])} students. Other sheets remain unchanged.')
    if not apply:return
    session=graph.call('POST',root+'/createSession',{'persistChanges':True});graph.s.headers['workbook-session-id']=session['id']
    try:
        if not sheet:
            sheet=graph.call('POST',root+'/worksheets/add',{'name':name});base=root+'/worksheets/'+quote(sheet['id'],safe='')
            graph.call('PATCH',base+"/range(address='AI1:AI3')",{'values':[[marker],[0],[data['methodology']]]})
        end=column(len(data['columns']));count=len(data['rows'])
        if legacy:
            graph.call('PATCH',base+f"/range(address='AG1:AG{max(old,count)+1}')",{'values':[[''] for _ in range(max(old,count)+1)]})
        graph.call('PATCH',base+"/range(address='AJ1:AM2')",{'values':[
            ['Timing weight','Code weight','First-pass weight','Focus weight'],
            [data['weights'][key] for key in ('timing','code','first_pass','focus')]]})
        # Text number formats preserve GTIDs and enrollment identifiers before data entry.
        graph.call('PATCH',base+f"/range(address='A1:C{count+1}')",{'numberFormat':[['@']*3 for _ in range(count+1)]})
        graph.call('PATCH',base+f"/range(address='A1:{end}1')",{'values':[data['columns']]})
        for start in range(0,count,100):
            values=[[v if v is not None else '' for v in row] for row in data['rows'][start:start+100]]
            graph.call('PATCH',base+f"/range(address='A{start+2}:{end}{start+len(values)+1}')",{'values':values})
            formulas=[[None]*len(data['columns']) for _ in values]
            for offset in range(len(values)):
                n=start+offset+2
                formulas[offset][3]=f'=IF(COUNT(E{n}:H{n})=0,"",ROUND(SUMPRODUCT(E{n}:H{n},$AJ$2:$AM$2),1))'
                for input_col,output_index,weight in zip('EFGH',range(8,12),('AJ','AK','AL','AM')):
                    formulas[offset][output_index]=f'=IF(ISNUMBER({input_col}{n}),{input_col}{n}*${weight}$2,"")'
            graph.call('PATCH',base+f"/range(address='A{start+2}:{end}{start+len(values)+1}')",{'formulas':formulas})
        if old>count:
            graph.call('PATCH',base+f"/range(address='A{count+2}:{end}{old+1}')",{'values':[['']*len(data['columns']) for _ in range(old-count)]})
        graph.call('POST',root+'/application/calculate',{'calculationType':'Full'})
        actual=graph.call('GET',base+f"/range(address='A1:{end}{count+1}')")['values']
        if actual[0]!=data['columns'] or len(actual)!=count+1:raise RuntimeError('Workbook read-back size/header verification failed.')
        for expected,row in zip(data['rows'],actual[1:]):
            if str(row[0])!=str(expected[0]) or str(row[1])!=str(expected[1]):raise RuntimeError('Workbook identifier verification failed.')
            if expected[3] is None:
                if row[3] not in ('',None):raise RuntimeError('Missing-data score should be blank.')
            elif not isinstance(row[3],(int,float)) or abs(row[3]-expected[3])>0.051:raise RuntimeError('Workbook score recalculation verification failed.')
        graph.call('PATCH',base+"/range(address='AI1:AI3')",{'values':[[marker],[count],[data['methodology']]]})
        print(f'Updated and verified {count} student rows. No email was sent.')
    finally:
        graph.call('POST',root+'/closeSession',{})
        graph.s.headers.pop('workbook-session-id',None)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--course',type=int,required=True)
    p.add_argument('--workbook',default=DEFAULT_WORKBOOK);p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args();client=Trellis(os.environ.get('TRELLIS_URL',''),os.environ.get('TRELLIS_API_TOKEN',''))
    data=validate(client.request('GET',f'/api/v1/courses/{a.course}/reports/submission-review/export/'),a.course)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.touch(mode=0o600,exist_ok=True);a.output.chmod(0o600)
        a.output.write_text(json.dumps(data,indent=2)+'\n');print(f'Saved private export for {data["total"]} students.')
    graph=Graph(os.environ.get('MS_GRAPH_ACCESS_TOKEN',''))
    try:sync(graph,data,a.workbook,a.apply)
    finally:graph.s.close();client.session.close()

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,requests.RequestException) as exc:raise SystemExit(str(exc))
