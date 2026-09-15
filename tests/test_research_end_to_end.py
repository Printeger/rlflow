import time
from pathlib import Path
from rlflow import engine,experiments,policy
from test_engine import harness,deliver,result_for
from test_packages import approved,specification
from test_experiments_v2 import spec,approve


def test_research_chain_uses_actual_runner_cpu_and_fresh_pi(harness):
    h=harness
    experiment=spec(h);experiment['stage_id']='PKG'
    output=h.store.root/'workspaces'/'run-output';output.mkdir()
    experiment['cwd']=str(output)
    package=specification(h);package['tasks']=package['tasks'][:1];package['tasks'][0]['research_mode']=True
    package['experiments']=[experiment]
    h.store.transact('FIXTURE_CONDITION','condition',lambda s:s['evidence'].update(condition={'id':'condition','sha256':'1'*64,'accepted':True}))
    approved(h,package)
    phases=[]
    for index in range(6):
        if index==4:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                state=engine.reconcile(h.store)
                task=state['tasks'][h.task_id]
                if task['status']=='QUEUED':break
                engine.dispatch_one(h.store)
                time.sleep(.03)
            assert task.get('research_job'),task
        sid=engine.dispatch_one(h.store);assert sid is not None
        state=h.store.replay();se=state['sessions'][sid];h.task_id=se['task_id'];role=se['role'];phases.append(role)
        result=result_for(h,sid)
        p=result['payload']
        if role=='PI':
            p.update(decision='STOP' if index==5 else 'CONTINUE',next_prediction='The controlled input distinguishes the competing explanations',task_interpretation=None)
        elif role=='Critic':
            p['hypotheses']=[{'statement':'controlled input predicts output','supporting_evidence':[],'counter_evidence':[],'discriminating_test':'run fixed CPU probe'}]
        elif role=='Designer':
            p.update(required_observations=['stdout','exit_code'],decision_rules=['correct output supports H1; failures are retained'],stop_conditions=['one run'])
            result['requested_actions']=[{'action':'REQUEST_EXPERIMENT','fields':[experiment['id']],'purpose':'test the fixed discriminating prediction','evidence_ids':[]}]
        elif role=='Evaluator':
            hid=state['research']['PKG']['cycles'][h.task_id]['hypotheses'][0]['id']
            p['evidence_coverage']=[hid+':SUPPORTED']
        state=deliver(h,sid,result)
        assert state['sessions'][sid]['status']=='ACCEPTED',state['sessions'][sid]
    assert phases==['PI','Critic','PI','Designer','Evaluator','PI']
    cycle=state['research']['PKG']['cycles'][h.task_id]
    assert cycle['valid_cycles']==1 and cycle['hypotheses'][0]['status']=='SUPPORTED'
    assert state['tasks'][h.task_id]['status']=='STOPPED'
    assert (output/'starts.txt').read_text()=='1'
    assert len(state['sessions'])==6 and state['stages']['PKG']['used_calls']==6
    assert len(state['decisions'])==3 and len(state['approvals'])==1
