import json
from pathlib import Path
import pytest
from rlflow import engine,evidence
from rlflow.store import Conflict,canonical,sha
from test_engine import harness,deliver,result_for
from test_packages import approved,step


def test_evidence_details_are_scoped_hashed_bounded_and_deduplicated(harness):
    h=harness;approved(h);state=step(h)
    sid=next(iter(state['sessions']));eid='E-'+sid
    request={'purpose':'inspect exact accepted interpretation','fields':['payload'],'evidence_ids':[eid]}
    first=evidence.detail(h.store,sid,request);version=h.store.replay()['version']
    assert evidence.detail(h.store,sid,request)==first and h.store.replay()['version']==version
    with pytest.raises(Conflict):evidence.detail(h.store,sid,{**request,'fields':['arbitrary_path']})
    with pytest.raises(Conflict):evidence.detail(h.store,sid,{**request,'evidence_ids':['unknown']})
    path=Path(state['sessions'][sid]['directory'])/'result.json';path.write_text('{}')
    with pytest.raises(Conflict):evidence.detail(h.store,sid,request)


def test_role_cannot_cite_an_unrelated_package_even_with_known_id(harness):
    h=harness;approved(h);sid=engine.dispatch_one(h.store);h.task_id=h.store.replay()['sessions'][sid]['task_id']
    h.store.transact('FIXTURE_PRIVATE_EVIDENCE','private',lambda s:s['evidence'].update(secret={'id':'secret','task_id':'another','package_id':'other','sha256':'f'*64,'accepted':True}))
    result=result_for(h,sid);result['evidence_refs']=['secret']
    state=deliver(h,sid,result)
    assert state['sessions'][sid]['status']=='REJECTED'
    assert 'Unreachable evidence' in state['sessions'][sid]['error']


def test_materialization_preserves_legacy_external_reference_boundary(harness,tmp_path):
    h=harness;state=h.store.replay();task=state['tasks'][h.task_id]
    state['evidence']['old']={'id':'old','accepted':True,'path':'/unmounted/historical.json','sha256':'f'*64}
    assert evidence.materialize(h.store,state,task,tmp_path)==[]


@pytest.mark.parametrize('kind,field,value',[('jobs','status','FAILED'),('literature','sources',[{'title':'negative evidence'}])])
def test_detail_serves_bound_runner_and_source_objects(harness,kind,field,value):
    from rlflow.store import atomic
    h=harness;approved(h);state=step(h);sid=next(iter(state['sessions']));task=state['tasks'][state['sessions'][sid]['task_id']]
    obj={field:value};path=h.store.root/kind/'bound-object';atomic(path/('receipt.json' if kind=='jobs' else 'result.json'),canonical(obj))
    record={'id':'bound','accepted':True,'task_id':task['id'],'package_id':task['package_id'],'path':str(path),'sha256':sha(obj)}
    if kind=='jobs':record['job_id']='bound-object'
    h.store.transact('FIXTURE_BOUND_SOURCE','bound',lambda s:s['evidence'].update(bound=record))
    result=evidence.detail(h.store,sid,{'purpose':'inspect raw source','fields':[field],'evidence_ids':['bound']})
    assert result[0]['fields'][field]==value
