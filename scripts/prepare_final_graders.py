"""Build independently authored native final-problem graders and verify them in Docker.

The source archive and references remain private course content, outside Git.
No legacy grading program is imported or executed.
"""
import argparse,hashlib,json,string,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runner'),str(ROOT/'scripts')]
from grading.spec import RunRequest
from grading.docker_executor import DockerExecutor
from grading.manifest import load_definition
from grading.engine import grade
from upload_native_graders import bundle_digest,private_json


def literal(value):return {'kind':'literal','value':value}
def choice(values):return {'kind':'choice','values':values}
def text(alphabet=string.ascii_uppercase,low=2,high=10):return {'kind':'string','min_length':low,'max_length':high,'alphabet':alphabet}
def items(rule,low,high):return {'kind':'list','min_length':low,'max_length':high,'items':rule}
def join(parts,separator=' '):return {'kind':'join','separator':separator,'items':{'kind':'sequence','items':parts}}
def record(fields):return {'kind':'record','fields':fields}

def plan(number,files):
    def function(target,args,**extra):return {'action':'function','target':target,'arguments':args,**extra}
    def fixed(target,args,**extra):return function(target,args,**extra)
    if number==1:
        fields=['short_name','long_name','iso_code','iso_short','iso_long','capital']
        nations=[dict(zip(fields,row)) for row in [('Albania','Republic of Albania',8,'AL','ALB','Tirana'),('Angola','Republic of Angola',24,'AO','AGO','Luanda')]]
        fixed_cases=[fixed('to_dictionaries',[rows],argument_constructors={'0':'Nation'}) for rows in [[],nations,nations[:1],nations*2]]
        descriptor=record({key:({'kind':'integer','min':1,'max':999} if key=='iso_code' else text(high=16)) for key in fields})
        return fixed_cases,[function('to_dictionaries',[items(descriptor,0,8)],argument_constructors={'0':'Nation'})]
    if number==2:
        names=['Addison Zook','Uma Irwin','David Joyner','Zelda Zenith','Amy Able']
        return [fixed('generate_name',['heronames.txt',n]) for n in names],[function('generate_name',[literal('heronames.txt'),join([text(),text()])],files={'heronames.txt':{'kind':'join','separator':'\n','items':items(text(low=2,high=12),52,52)}})]
    if number==3:
        hands=['A3','A39','A397','A397K','AA5','AAA4','AA9','0K2','AAAA','K7','A6','2345']
        return [fixed('next_move',[hand]) for hand in hands],[function('next_move',[text('A234567890JQK',2,8)])]
    if number==4:
        empty=[[None]*7 for _ in range(6)];boards=[empty]
        from copy import deepcopy
        for symbol in ['X','O']:
            for start,delta in [((5,0),(0,1)),((2,0),(1,0)),((2,1),(1,1)),((2,5),(1,-1))]:
                board=deepcopy(empty)
                for i in range(4):board[start[0]+delta[0]*i][start[1]+delta[1]*i]=symbol
                boards.append(board)
        # Single-player domains avoid ambiguous boards with two winners.
        templates=[function('check_winner',[items(items(choice([None,symbol]),7,7),6,6)]) for symbol in ['X','O']]
        return [fixed('check_winner',[board]) for board in boards],templates
    if number==5:
        pairs=[('one two three four five','one two three four five'),('a b c d','a b c d'),('red blue gold white black green','x red blue gold white black green y'),('a b c d e x p q r s t u','p q r s t u'),('alpha beta','gamma delta')]
        fixed_cases=[fixed('check_plagiarism',['test_left.txt','test_right.txt'],files={'test_left.txt':a,'test_right.txt':b}) for a,b in pairs]
        templates=[]
        for phrase in ['one two three four five six','red blue green gold','alpha beta gamma delta epsilon zeta eta theta']:
            fixtures={name:join([text(string.ascii_lowercase),literal(phrase),text(string.ascii_lowercase)]) for name in ['test_left.txt','test_right.txt']}
            templates.append(function('check_plagiarism',[literal('test_left.txt'),literal('test_right.txt')],files=fixtures))
        return fixed_cases,templates
    if number==6:
        import csv,io
        opponents=sorted({r['Opponent'] for r in csv.DictReader(io.StringIO(files['georgia_tech_football.csv']))})
        return [fixed('all_time_record',[team]) for team in ['Clemson','Duke','North Carolina','Georgia','No such opponent']],[function('all_time_record',[choice(opponents)])]
    if number==10:
        fixed_cases=[fixed('encrypt',[s]) for s in ['', 'PS. Hello, worlds','Jelly!','AA','DAVIO','X','Hello 1301']]+[fixed('decrypt',[s]) for s in ['QLGRQTVZIBTYQZ','AV','DY','DA','XX','']]
        return fixed_cases,[function('encrypt',[text(string.ascii_letters+' !0123456789',1,35)]),function('decrypt',[text('DAVIOYNERBCFGHKLMPQSTUWXZ',12,12)])]
    raise ValueError('Unsupported final coding problem.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=ROOT/'var/vocareum-final-problems');parser.add_argument('--references',type=Path,required=True);parser.add_argument('--inspection',type=Path,default=ROOT/'var/api-reports/final-pset-inspection.json');parser.add_argument('--out',type=Path,default=ROOT/'var/native-final-graders');args=parser.parse_args()
    inspection=json.loads(args.inspection.read_text());by_title={row['item']['title']:row for row in inspection if row['item']['metadata'].get('kind')=='coding'}
    executor=DockerExecutor();rows=[];translation={}
    for path in sorted(args.source.glob('exercises/*/*/manifest.json')):
        m=json.loads(path.read_text());number=int(m['part_name'].split()[-1]);source=path.parent
        matched=by_title[m['part_name']];detail=matched['detail'];reference=(args.references/f'{number}.py').read_text()
        files={p.name:p.read_text() for p in (source/'startercode').iterdir() if p.is_file() and not p.name.startswith(('sample_answer','full_results'))}
        entry=m['entrypoint'];cases,templates=plan(number,files)
        for i,case in enumerate(cases,1):
            observation=executor.run(RunRequest(source=reference,action='function',target=case['target'],arguments=case['arguments'],files={**files,**case.get('files',{})},argument_constructors=case.get('argument_constructors',{})))
            if observation.status!='ok':raise RuntimeError(f'Final problem {number} reference failed: {observation.status}')
            case.update(id=f'fixed-{i}',label=f'Test {i}',expected=observation.value)
        definition={'version':1,'scoring':'all_or_nothing','cases':cases,'random_cases':{'count':6,'oracle_path':'grader/reference.py','templates':templates}}
        exercise=load_definition(definition)
        # A separately assembled submission includes the original exercise's test calls.
        starter=files[entry];marker='#Add your code here!'
        positive=reference+'\n'+starter if marker not in starter else starter.replace(marker,reference)
        if number==6:positive=reference+'\n'+starter[starter.index('#Below are some lines'):]
        for seed in [1301,2025]:
            result=grade(positive,exercise,executor,files=files,oracle_source=reference,oracle_files=files,random_seed=seed)
            if not result['passed']:raise RuntimeError(f'Final problem {number} positive control failed: '+result['full_output'][:1000])
        negatives=['raise RuntimeError("Deliberately wrong control")\n']
        target=cases[0]['target'];negatives.append('def '+target+'(*args):\n    return '+repr(cases[0]['expected'])+'\n')
        for negative in negatives:
            if grade(negative,exercise,executor,files=files,oracle_source=reference,oracle_files=files,random_seed=1301)['passed']:raise RuntimeError('Incorrect control passed.')
        folder=args.out/f'part-{matched["item"]["id"]}';folder.mkdir(parents=True,exist_ok=True)
        private_json(folder/'autograder.json',definition)
        for filename,text_value in [('correct.py',positive),('reference.py',reference),*[(f'incorrect-{i}.py',s) for i,s in enumerate(negatives,1)]]:
            (folder/filename).write_text(text_value);(folder/filename).chmod(0o600)
        row={'part_id':matched['item']['id'],'assignment_id':detail['lesson'],'title':m['part_name'],'vocareum_part_id':str(m['part_id']),'status':'ready','expected_revision_id':detail['revision'],'entrypoint':entry,'definition':str((folder/'autograder.json').relative_to(args.out)),'reference':str((folder/'reference.py').relative_to(args.out)),'randomization':'per_submission','validation':{'status':'passed','positive':str((folder/'correct.py').relative_to(args.out)),'negatives':[str((folder/f'incorrect-{i}.py').relative_to(args.out)) for i in range(1,len(negatives)+1)]}}
        row['validation']['bundle_sha256']=bundle_digest(row,definition,positive,negatives,reference);rows.append(row)
        private_json(args.out/'manifest.json',{'version':1,'course_id':1,'parts':rows})
        private_json(source/'definition.json',definition);(source/'native-reference.py').write_text(reference);(source/'private/sample_answer.py').write_text(reference)
        translation[str(source.relative_to(args.source))]={'status':'ready','entrypoint':entry,'checks':len(cases),'random_cases':6,'validated_seeds':[1301,2025]}
        private_json(args.source/'translation-report.json',translation)
        print(f'Final {number}: {len(cases)} fixed + 6 fresh cases; correct and two incorrect controls verified.',flush=True)

if __name__=='__main__':main()
