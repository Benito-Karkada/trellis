"""Bounded synthetic student journeys. Requires TRELLIS_LOAD_FIXTURE."""
import json
import os
import random
import time
import uuid
from collections import deque
from pathlib import Path
import gevent
from locust import HttpUser, between, events, task
from locust.exception import StopUser

fixture = json.loads(Path(os.environ['TRELLIS_LOAD_FIXTURE']).read_text())
accounts = deque(enumerate(fixture['accounts']))
MAX_USERS = 20
MAX_JOBS = 160
submitted_jobs = 0
stopping = False
burst_epoch = None
profile = os.environ.get("TRELLIS_LOAD_PROFILE", "mixed")
active_users = int(os.environ.get("TRELLIS_LOAD_USERS", "10"))


def stop_test(environment, reason):
    global stopping
    if stopping:return
    stopping = True
    environment.process_exit_code = 2
    print('LOAD TEST STOPPED:', reason, flush=True)
    gevent.spawn(environment.runner.quit)


@events.test_start.add_listener
def validate_start(environment, **kwargs):
    global burst_epoch
    burst_epoch = time.monotonic() + 35
    if environment.host.rstrip('/') != fixture['url'].rstrip('/'):
        stop_test(environment, 'Target host does not match the private fixture.')
    if environment.parsed_options.num_users and environment.parsed_options.num_users > MAX_USERS:
        stop_test(environment, 'Maximum is 20 synthetic users.')
    if len(fixture['accounts']) > MAX_USERS:
        stop_test(environment, 'Fixture exceeds the 20-user limit.')


@events.request.add_listener
def circuit_breaker(request_type, name, response_time, response_length, exception=None, context=None, **kwargs):
    # The User supplies its environment; never log response bodies/passwords.
    environment = (context or {}).get('environment')
    if not environment:return
    total = environment.stats.total
    if total.num_requests >= 50 and total.fail_ratio > .10:
        stop_test(environment, 'More than 10% of requests are failing.')


class Student(HttpUser):
    wait_time = between(5, 10) if profile == "burst" else between(15, 25)
    def on_start(self):
        if not accounts:raise StopUser()
        self.index, account = accounts.popleft()
        self.client.trust_env = False
        self.phase = 0
        self.burst_round = 0
        self.tab_id = str(uuid.uuid4())
        self.request('GET','/api/session/','session')
        self.request('POST','/api/auth/login/','login',{'email':account['email'],'password':account['password']})
        outline = self.request('GET','/api/outline/','course outline')
        if not outline or outline.get('term') != fixture.get('expected_term','loadtest-'+fixture['run_id']):
            stop_test(self.environment,'Synthetic account did not enter its isolated course.');raise StopUser()
        self.request('POST',f"/api/assignments/{fixture['lesson_id']}/open/",'open assignment',{})

    def context(self):return {'environment':self.environment}

    def request(self,method,path,name,body=None):
        headers={'Referer':self.host.rstrip('/')+'/','X-CSRFToken':self.client.cookies.get('csrftoken','')}
        with self.client.request(method,path,name=name,json=body if method=='POST' else None,
                headers=headers,timeout=20,catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f'HTTP {response.status_code}');return None
            try:data=response.json()
            except ValueError:response.failure('Invalid JSON');return None
            if data.get('error'):response.failure('Application error');return None
            return data

    def open_part(self,item):
        self.request('POST',f"/api/assignments/{item.get('lesson_id',fixture['lesson_id'])}/open/",'open assignment',{})
        self.request('POST',f"/api/viewed/{item['activity']}/",'view part',{})
        return self.request('GET',f"/api/studio/{item['activity']}/",'open '+('coding workspace' if 'entrypoint' in item or item==fixture['coding'] else 'content'))

    @task(3)
    def browse(self):
        if self.coordinated_burst():return
        self.request('GET','/api/outline/','course outline')
        self.open_part(fixture['reading'])

    @task(1)
    def answer_question(self):
        if self.coordinated_burst():return
        item=fixture['native'];self.open_part(item)
        result=self.request('POST',f"/api/submit-native/{item['revision']}/",'submit native question',{'responses':item.get('responses',{'q1':'a'})})
        if result and (not result.get('passed') or (not result.get('practice') and float(result.get('recorded_score',0))!=float(item.get('maximum','1')))):
            self.environment.events.request.fire(request_type='CHECK',name='native score',response_time=0,response_length=0,
                exception=RuntimeError('Native answer did not earn its expected point.'),context=self.context())

    def coordinated_burst(self):
        if profile != 'burst' or self.index >= (active_users+1)//2:return False
        slot=self.burst_round
        target=burst_epoch+slot*90
        while time.monotonic()<target:
            if stopping or self.environment.runner.state not in {'running','spawning'}:raise StopUser()
            gevent.sleep(min(1,target-time.monotonic()))
        if stopping or self.environment.runner.state != 'running':raise StopUser()
        self.burst_round+=1
        workloads=fixture.get('workloads') or [{**fixture['coding'],'entrypoint':'main.py',
            'correct_source':fixture['correct_source'],'wrong_source':fixture['wrong_source'],
            'correct_stdout':'5\n','wrong_stdout':'-1\n'}]
        item=workloads[(self.index//2+slot)%len(workloads)]
        operation='run' if (self.index+slot)%2 else 'submit'
        correct=slot%3!=0
        self.execute_code(item,operation,correct)
        return True

    @task(1)
    def code(self):
        if self.coordinated_burst():return
        if profile=='burst':
            self.browse();return
        item={**fixture['coding'],'entrypoint':'main.py','correct_source':fixture['correct_source'],
            'wrong_source':fixture['wrong_source'],'correct_stdout':'5\n','wrong_stdout':'-1\n'}
        phases=[('submit',True)] if self.index%3==0 else [('run',False),('submit',False),('run',True),('submit',True)]
        operation,correct=phases[self.phase%len(phases)];self.phase+=1
        self.execute_code(item,operation,correct)

    def execute_code(self,item,operation,correct):
        global submitted_jobs
        if stopping:raise StopUser()
        if submitted_jobs >= MAX_JOBS:
            stop_test(self.environment,'Reached the bounded execution budget.');raise StopUser()
        data=self.open_part(item)
        if not data:return
        files=dict(data['workspace']);files[item['entrypoint']]=item['correct_source' if correct else 'wrong_source']
        start=time.monotonic()
        created=self.request('POST',f"/api/execute/{item['revision']}/",operation+' enqueue',{'operation':operation,'entrypoint':item['entrypoint'],'files':files})
        if not created:return
        submitted_jobs+=1
        deadline=start+60
        while time.monotonic()<deadline:
            gevent.sleep(2)
            state=self.request('GET',f"/api/jobs/{created['id']}/",'poll execution job')
            if not state:continue
            if state['status'] in {'completed','failed'}:
                result=state.get('result',{});error=None
                if state['status']!='completed' or result.get('error'):error=RuntimeError('Execution service failed.')
                elif operation=='submit' and bool(result.get('passed'))!=correct:error=RuntimeError('Grading verdict differs from known answer.')
                elif operation=='run' and (result.get('execution_status')!='ok' or (item.get('correct_stdout' if correct else 'wrong_stdout') is not None and result.get('stdout')!=item['correct_stdout' if correct else 'wrong_stdout'])):error=RuntimeError('Run output differs from known answer.')
                self.environment.events.request.fire(request_type='WORKFLOW',name=operation+' end-to-end',response_time=(time.monotonic()-start)*1000,
                    response_length=0,exception=error,context=self.context())
                self.request('GET','/api/outline/','course outline')
                self.request('POST',f"/api/assignments/{item.get('lesson_id',fixture['lesson_id'])}/pace/",'pace check',{})
                return
        self.environment.events.request.fire(request_type='WORKFLOW',name=operation+' end-to-end',response_time=(time.monotonic()-start)*1000,
            response_length=0,exception=RuntimeError('Execution did not complete in 60 seconds.'),context=self.context())
        stop_test(self.environment,'Execution queue stalled for 60 seconds.')

    @task(1)
    def focus_signal(self):
        if self.coordinated_burst():return
        episode=str(uuid.uuid4())
        for state,elapsed in [('away',0),('hidden',0),('back',3000)]:
            self.request('POST',f"/api/assignments/{fixture['lesson_id']}/focus/",'synthetic focus signal',
                {'event_id':str(uuid.uuid4()),'episode_id':episode,'tab_id':self.tab_id,'state':state,'reason':'tab','elapsed_ms':elapsed,'part_id':fixture['coding']['activity']})

    def on_stop(self):
        self.request('POST','/api/auth/logout/','logout',{})
