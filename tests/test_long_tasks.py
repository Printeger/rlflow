import copy,json,subprocess,sys,shlex
import pytest
from pathlib import Path
from rlflow import engine,packages,policy,research
from rlflow.store import Conflict,Store,atomic,canonical
from test_engine import harness,result_for,deliver,REAL_PACKET
from test_packages import approved,specification,step


def goal(h):
    spec=specification(h);spec['tasks']=spec['tasks'][:1];spec['budget']={'role_calls':40}
    spec['decomposition']={'max_tasks':12,'max_depth':3}
    return spec


def split(h,children=None):
    sid=engine.dispatch_one(h.store);s=h.store.replay();h.task_id=s['sessions'][sid]['task_id'];t=s['tasks'][h.task_id]
    assert s['sessions'][sid]['role']=='PI'
    r=result_for(h,sid);r['payload']['task_interpretation'].update(stage_id='PKG',budget=s['stages']['PKG']['budget'],acceptance_criteria=[c['id'] for c in t['criteria']])
    children=children or [{'id':k,'text':'Implement and verify subproblem '+k,'depends_on':deps,'condition_ids':[c['id'] for c in t['criteria']]} for k,deps in [('first',[]),('second',['first'])]]
    r['requested_actions']=[{'action':'REQUEST_DECOMPOSITION','fields':[json.dumps({'children':children})],'purpose':'refine approved parent goal','evidence_ids':[]}]
    return sid,deliver(h,sid,r)


def actual_step(h,fail_once=False):
    sid=engine.dispatch_one(h.store);assert sid
    state=h.store.replay();se=state['sessions'][sid];h.task_id=se['task_id'];t=state['tasks'][h.task_id]
    if se['role']=='Engineer':
        check='not isinstance(value,int)' if fail_once else 'type(value) is not int'
        (h.repo/'parser.py').write_text('def parse(value):\n    if '+check+' or value < 0: raise ValueError("invalid")\n    return value\n')
    r=result_for(h,sid)
    if se['role']=='PI':
        r['payload']['task_interpretation'].update(stage_id='PKG',budget=state['stages']['PKG']['budget'],acceptance_criteria=[c['id'] for c in t['criteria']])
    if se['role']=='Evaluator':
        program='import runpy; f=runpy.run_path("parser.py")["parse"]; errors=[]\nfor v in [-1,True,False,1.2,"1",None]:\n try: f(v); errors.append(repr(v))\n except (ValueError,TypeError): pass\nassert f(0)==0 and f(2)==2\nprint(errors)\nraise SystemExit(bool(errors))'
        argv=[sys.executable,'-c',program];run=subprocess.run(argv,cwd=h.repo,capture_output=True,text=True)
        d=Path(se['directory']);atomic(d/'independent-check.stdout',run.stdout.encode());atomic(d/'independent-check.stderr',run.stderr.encode())
        with (d/'result.json.commands.jsonl').open('ab') as out:out.write(canonical({'argv':argv,'command':shlex.join(argv),'exit_code':run.returncode,'stdout':run.stdout,'timed_out':False})+b'\n')
        if run.returncode:
            fail=result_for(h,sid,'FAIL')['payload'];r['payload']=fail
            for f in fail['findings']:f.update(contract=t['criteria'][0]['id'],evidence_refs=[next(iter(state['evidence']))])
        r['payload']['evidence_coverage']=[c['id'] for c in t['criteria']]
    return deliver(h,sid,r)


def test_one_goal_nested_decomposition_restart_rework_integration(harness):
    h=harness;p=approved(h,goal(h));root=p['tasks'][0]
    _,s=split(h);first,second=s['tasks'][root]['children']
    _,s=split(h);nested=s['tasks'][first]['children']
    assert len(s['tasks'])==5 and s['tasks'][root]['status']=='WAITING_CHILDREN'
    # Reconstruct the dispatcher store between every role to exercise persisted planning.
    roles=[];failed=False
    for _ in range(30):
        h.store=Store(h.store.root)
        s=h.store.replay()
        queued=[t for t in s['tasks'].values() if t['status']=='QUEUED' and packages.runnable(s,t)]
        if not queued:break
        t=min(queued,key=lambda x:x['order']);role=t['next_role'];roles.append((t['id'],role))
        s=actual_step(h,fail_once=not failed)
        if role=='Evaluator' and not failed:failed=True
        assert not any(t['status'] in {'CONTRACT_DECISION','RECONCILE'} for t in s['tasks'].values()),s['tasks']
    assert s['goals']['PKG']['status']=='DONE'
    assert len(s['approvals'])==1 and s['stages']['PKG']['reserved_calls']==0
    assert s['tasks'][root]['integration_review'] and s['tasks'][first]['integration_review']
    assert roles[-1]==(root,'Evaluator') and engine.dispatch_one(h.store) is None
    assert s['stages']['PKG']['used_calls']==len(roles)+2
    assert h.store.rebuild()==s


@pytest.mark.parametrize('mutation',[
 lambda c:c[0]['condition_ids'].append('new-contract'),
 lambda c:c[0].update(budget={'role_calls':1000}),
 lambda c:c[0]['depends_on'].append('second'),
 lambda c:c[0].update(module_roots=['/']),
])
def test_decomposition_cannot_expand_authority_or_create_cycles(harness,mutation):
    h=harness;approved(h,goal(h));children=[{'id':'first','text':'first','depends_on':[],'condition_ids':['C-a']},{'id':'second','text':'second','depends_on':['first'],'condition_ids':['C-a']}];mutation(children)
    sid,s=split(h,children)
    assert s['sessions'][sid]['status']=='REJECTED' and len(s['tasks'])==1


def test_dynamic_plan_cannot_be_injected_or_changed_after_acceptance(harness):
    h=harness;approved(h,goal(h));_,s=split(h);child=s['packages']['PKG']['tasks'][-1]
    s['tasks'][child]['criteria'][0]['description']='weakened'
    with pytest.raises(Conflict):policy.require_stage(s,'PKG')


def test_legacy_static_approval_does_not_gain_decomposition(harness):
    h=harness;approved(h);sid,s=split(h)
    assert s['sessions'][sid]['status']=='REJECTED' and len(s['tasks'])==3


def test_long_context_is_bounded_and_history_is_lossless(harness):
    h=harness;p=approved(h,goal(h));s=h.store.replay();t=s['tasks'][p['tasks'][0]]
    root=s.setdefault('research',{}).setdefault('PKG',{});cycle=research.record(s,t)
    cycle['counterevidence']=[{'id':str(i),'summary':'negative result '+('detail '*500)} for i in range(200)]
    for i in range(300):
        s['decisions'][str(i)]={'id':str(i),'task_id':t['id'],'payload':{'analysis':'old '*500},'counterevidence':['negative '+str(i)]}
        s['evidence'][str(i)]={'id':str(i),'task_id':t['id'],'accepted':True,'summary':'raw measurement','sha256':'f'*64}
    directory=h.store.root/'roles'/'packet';directory.mkdir(parents=True)
    session={'id':'packet','role':'PI','input_state_version':s['version'],'scratch':str(directory/'scratch'),'directory':str(directory),'role_definition':{'developer_instructions':'interpret'}}
    prompt,_=REAL_PACKET(h.store,s,t,session)
    import tiktoken
    assert len(tiktoken.get_encoding('cl100k_base').encode(prompt))<15000
    archive=json.loads((directory/'evidence/context-history.json').read_text())
    assert len(archive['history']['research']['counterevidence'])==200
    assert len(archive['history']['decisions'])==300
    assert 'history_index' in prompt and 'REQUEST_DECOMPOSITION' in prompt


def test_research_three_cycles_cold_review_then_goal_and_next_task(harness):
    import time
    from test_experiments_v2 import spec as experiment_spec
    h=harness;package=goal(h);package['tasks'][0]['research_mode']=True
    package['tasks'].append({'id':'follow','text':'integrate observed result','depends_on':['a'],'criteria':[{'id':'C-follow','description':'verify integrated parser','layer':'cpu'}]})
    output=h.store.root/'workspaces'/'observations';output.mkdir()
    original=experiment_spec(h);original.update(stage_id='PKG',cwd=str(output))
    package['experiments']=[{**copy.deepcopy(original),'id':'trial-'+str(i),'seed':i} for i in range(3)]
    h.store.transact('FIXTURE_CONDITION','condition',lambda s:s['evidence'].update(condition={'id':'condition','sha256':'1'*64,'accepted':True}))
    p=approved(h,package);root=p['tasks'][0];roles=[];cold=[]
    for _ in range(25):
        h.store=Store(h.store.root);s=h.store.replay();task=s['tasks'][root]
        if task['status']=='DONE':break
        if task['status']=='WAITING_EXPERIMENT':
            engine.dispatch_one(h.store)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                s=engine.reconcile(h.store)
                if s['tasks'][root]['status']=='QUEUED':break
                time.sleep(.03)
        sid=engine.dispatch_one(h.store);assert sid
        s=h.store.replay();se=s['sessions'][sid];h.task_id=se['task_id'];task=s['tasks'][root];cycle=research.record(s,task)
        roles.append(se['role']);r=result_for(h,sid);payload=r['payload']
        if se['role']=='PI':
            payload.update(decision='CONTINUE',task_interpretation=None,next_prediction='compare the next frozen trial against this condition')
            if research.completion_ready(s,task):r['requested_actions']=[{'action':'REQUEST_COMPLETE','fields':[],'purpose':'all independently verified goal conditions satisfied','evidence_ids':[]}]
        elif se['role']=='Critic':payload['hypotheses']=[{'statement':'controlled result predicts contract','supporting_evidence':[],'counter_evidence':[],'discriminating_test':'fixed trial list'}]
        elif se['role']=='Designer':
            trial=package['experiments'][len(cycle['experiments'])]
            payload.update(required_observations=['stdout','exit_code'],decision_rules=['retain negative and inconclusive observations'],stop_conditions=['one exact trial'])
            r['requested_actions']=[{'action':'REQUEST_EXPERIMENT','fields':[trial['id']],'purpose':'execute next approved trial','evidence_ids':[]}]
        elif se['role']=='Evaluator':
            if task.get('cold_review'):cold.append(task['cold_review'])
            else:
                index=len(cycle['experiments']);hid=cycle['hypotheses'][0]['id']
                payload.update(verdict=['FAIL','INCONCLUSIVE','PASS'][index],findings=[],evidence_coverage=[hid+':'+['FALSIFIED','INCONCLUSIVE','SUPPORTED'][index]])
                if index==2:
                    eid='E-'+task['research_job'];e=s['evidence'][eid]
                    payload['evidence_coverage']+=['C-a','OBSERVATION:'+json.dumps({'condition_id':'C-a','evidence_id':eid,'evidence_sha256':e['sha256'],'explanation':'independent inspection confirms frozen observation contract'})]
        s=deliver(h,sid,r);assert s['sessions'][sid]['status']=='ACCEPTED',s['sessions'][sid]
    assert s['tasks'][root]['status']=='DONE' and cold==['RAW','INTERPRETED']
    assert s['packages']['PKG']['status']=='ACTIVE'
    assert len(s['jobs'])==3 and (output/'starts.txt').read_text()=='3'
    assert len(s['research']['PKG']['cycles'][root]['negative_results'])==2
    for _ in range(3):s=step(h)
    assert s['goals']['PKG']['status']=='DONE' and len(s['approvals'])==1
    assert engine.dispatch_one(h.store) is None


def test_pi_cannot_declare_research_done_without_evaluator(harness):
    h=harness;package=goal(h);package['tasks'][0]['research_mode']=True;approved(h,package)
    sid=engine.dispatch_one(h.store);s=h.store.replay();h.task_id=s['sessions'][sid]['task_id'];r=result_for(h,sid)
    r['payload'].update(decision='CONTINUE',task_interpretation=None)
    r['requested_actions']=[{'action':'REQUEST_COMPLETE','fields':[],'purpose':'claim success without proof','evidence_ids':[]}]
    s=deliver(h,sid,r)
    assert s['sessions'][sid]['status']=='REJECTED' and s['goals']['PKG']['status']=='ACTIVE'


def test_goal_cli_presents_exact_envelope_without_starting_roles(harness,capsys):
    from rlflow import cli
    h=harness;value=goal(h);value['criteria']=value.pop('tasks')[0]['criteria'];value.pop('decomposition')
    path=h.store.root/'goal.json';path.write_text(json.dumps(value))
    before=h.store.replay();assert cli.main(['--state-dir',str(h.store.root),'start','--goal-file',str(path)])==0
    shown=json.loads(capsys.readouterr().out);package=shown['content']['package']
    assert package['decomposition']=={'max_tasks':32,'max_depth':4}
    assert len(package['tasks'])==1 and package['tasks'][0]['text']==value['goal']
    after=h.store.replay();assert after['sessions']==before['sessions'] and after['approvals']==before['approvals']


def test_decomposition_preserves_budget_and_pause_during_parent_integration(harness):
    h=harness;v=goal(h);v['budget']['role_calls']=2;p=approved(h,v);root=p['tasks'][0];split(h)
    packages.pause(h.store,'PKG',True);assert engine.dispatch_one(h.store) is None
    packages.pause(h.store,'PKG',False);s=step(h)
    assert s['stages']['PKG']['used_calls']==2
    assert engine.dispatch_one(h.store) is None
    s=h.store.replay();assert s['stages']['PKG']['used_calls']==2 and s['tasks'][root]['status']=='WAITING_CHILDREN'
    assert len(s['approvals'])==1


def test_context_uses_event_order_not_renamed_object_ids():
    from rlflow.context import project
    decisions=[{'id':str(100-i),'event_sequence':i} for i in reversed(range(20))]
    evidence=[{'id':str(100-i),'event_sequence':i} for i in reversed(range(30))]
    _,_,ds,es,_,_=project({}, {}, decisions,evidence)
    assert [x['event_sequence'] for x in ds]==list(range(15,20))
    assert [x['event_sequence'] for x in es]==list(range(18,30))
