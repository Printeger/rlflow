import copy
from pathlib import Path
import pytest
from rlflow import packages,policy,engine
from rlflow.governance import reserve_policy,remaining,reserve,settle,route
from rlflow.resources import admit
from rlflow.store import Conflict
from test_engine import harness,deliver,result_for
from test_packages import approved


def step(h):
    sid=engine.dispatch_one(h.store);assert sid is not None
    state=h.store.replay();session=state["sessions"][sid];h.task_id=session["task_id"];task=state["tasks"][h.task_id]
    result=result_for(h,sid)
    if session["role"]=="PI":result["payload"]["task_interpretation"].update(stage_id="PKG",module_roots=state["stages"]["PKG"]["module_roots"],budget=state["stages"]["PKG"]["budget"],acceptance_criteria=[c["id"] for c in task["criteria"]])
    elif session["role"]=="Engineer":result["payload"]["changes"]=[]
    elif session["role"]=="Evaluator":result["payload"]["evidence_coverage"]=[c["id"] for c in task["criteria"]]
    return deliver(h,sid,result)


def specification(h,mode='compatible_cpu'):
    import sys,hashlib
    executable=Path(sys.executable).resolve()
    environment={'python':{'path':str(executable),'version':sys.version.split()[0],'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}}
    return {'schema_version':'rlflow-package/2','id':'PKG','goal':'parser integration','repo':str(h.repo),
            'module_roots':['parser.py'],'protected_paths':['.git'],
            'tasks':[{'id':'a','text':'verify parser','depends_on':[],'criteria':[{'id':'C','description':'parser accepts valid values','layer':'cpu'}]}],
            'budget':{'role_calls':10,'wall_seconds':100},'per_call_seconds':5,'command_seconds':5,
            'inputs':{'source_files':['parser.py'],'data_references':[],'output_directories':['output'],'environment':environment},
            'routing':{'public_control':False,'change_categories':['ENGINEERING_FIX'],'specification_complete':True},
            'resource_policy':{'mode':mode,'memory_max':64*1024**2,'cpu_max':'20000 100000','pids_max':8,'disk_bytes':64*1024**2,'disk_inodes':1000,'cpu_seconds':10}}


def test_new_package_low_route_and_final_integration(harness):
    h=harness;p=approved(h,specification(h));a,final=p['tasks']
    assert h.store.get('tasks',a)['next_role']=='Engineer'
    for _ in range(2):state=step(h)
    assert state['tasks'][a]['status']=='DONE'
    assert state['goals']['PKG']['status']=='ACTIVE' and state['tasks'][final]['status']=='QUEUED'
    for _ in range(3):state=step(h)
    assert state['tasks'][final]['status']=='DONE' and state['goals']['PKG']['status']=='DONE'
    assert state['stages']['PKG']['pool_usage']['ordinary']['used_calls']==2
    assert state['stages']['PKG']['pool_usage']['integration']['used_calls']==3
    assert state['stages']['PKG']['budget_reserves']['recovery']['calls']==2


def test_outputs_are_outside_candidate_hash_and_diff(harness):
    h=harness;p=approved(h,specification(h));task=h.store.get('tasks',p['tasks'][0])
    before=engine.envelope_candidate(task);identity=policy.candidate(h.repo,task['input_contract'])
    output=h.repo/'output';output.mkdir()
    with (output/'large.bin').open('wb') as f:f.truncate(2*1024**3)
    assert policy.candidate(h.repo,task['input_contract'])==identity
    assert engine.envelope_candidate(task)==before


def test_strict_missing_quota_refuses_before_reservation(harness):
    h=harness;approved(h,specification(h,'strict'));before=h.store.replay()
    with pytest.raises(Conflict,match='quota'):engine.dispatch_one(h.store)
    after=h.store.replay();assert after==before


def test_reserves_not_spendable_by_ordinary_and_unknown_retained(harness):
    h=harness;spec=packages.validate(specification(h),h.store.root)
    stage={'budget_reserves':spec['budget_reserves']};task={};session={'limit':5}
    for i in range(stage['budget_reserves']['ordinary']['calls']):
        current={'limit':5};reserve(stage,current,task);settle(stage,current,{'model_usage':{'state':'USED'},'elapsed_seconds':5})
    with pytest.raises(Conflict):reserve(stage,session,task)
    reserve(stage,session,{'recovery_source':'failed-session'})
    before=copy.deepcopy(stage);settle(stage,session,{'model_usage':{'state':'UNKNOWN'},'elapsed_seconds':1})
    assert stage==before and remaining(stage,{'final_integration':True})['role_calls']==3


def test_insufficient_budget_and_high_risk_route(harness):
    h=harness;spec=specification(h);spec['budget']['role_calls']=6
    with pytest.raises(Conflict,match='minimum'):packages.validate(spec,h.store.root)
    spec=specification(h);spec['routing']['public_control']=True
    approved(h,spec);task=h.store.get('tasks',h.store.get('packages','PKG')['tasks'][0])
    assert task['route']==['PI','Critic','Engineer','Evaluator']
    state=step(h);assert state['tasks'][task['id']]['next_role']=='Critic'


def test_child_local_condition_cannot_close_parent_and_split_budget_is_checked(harness):
    import json
    from rlflow.decomposition import parse,apply
    h=harness;spec=specification(h);spec['budget']={'role_calls':30,'wall_seconds':300};spec['routing']['specification_complete']=False
    spec['decomposition']={'max_tasks':8,'max_depth':2}
    package=approved(h,spec);state=h.store.replay();task=state['tasks'][package['tasks'][0]]
    session={'id':'synthetic-parser-test','role':'PI'}
    child={'id':'local','text':'check parser boundary','depends_on':[],'condition_ids':['C'],
           'local_criteria':[{'id':'LOCAL','description':'boundary holds','layer':'cpu','parent_condition_id':'C'}]}
    action={'fields':[json.dumps({'children':[child]})]}
    apply(state,task,session,action)
    derived=state['tasks'][task['children'][0]]
    assert derived['criteria'][0]['id']=='LOCAL' and derived['criterion_parents']=={'LOCAL':'C'}
    derived['status']='DONE';packages.refresh(state,'PKG')
    assert task['integration_review'] and task['status']=='QUEUED' and state['goals']['PKG']['status']=='ACTIVE'
    assert not task['condition_evidence']
    fresh=h.store.replay();parent=fresh['tasks'][package['tasks'][0]]
    fresh['stages']['PKG']['pool_usage']={'ordinary':{'used_calls':23}}
    with pytest.raises(Conflict,match='minimum'):parse(fresh,parent,session,action)
