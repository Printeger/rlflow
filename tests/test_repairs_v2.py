import pytest
from rlflow import engine,repairs
from rlflow.store import Conflict
from test_engine import harness,deliver,result_for
from test_packages import approved


def test_infra_repair_uses_original_package_pool_and_cannot_write_policy(harness):
    h=harness;approved(h);sid=engine.dispatch_one(h.store);state=h.store.replay();se=state['sessions'][sid]
    h.task_id=se['task_id'];result=result_for(h,sid)
    result['payload']['task_interpretation'].update(stage_id='PKG',budget=state['stages']['PKG']['budget'],acceptance_criteria=['C-a'])
    deliver(h,sid,result,code=7)
    def fail(s):
        s['tasks'][h.task_id]['status']='INFRASTRUCTURE_ERROR'
        repairs.register_in(s,se,{'kind':'INFRASTRUCTURE','code':'OUTPUT_SCHEMA_REJECTED'})
    h.store.transact('FIXTURE_INFRA','fail',fail)
    rid=next(iter(h.store.replay()['repairs']))
    assert repairs.prepare(h.store,rid)
    state=h.store.replay();repair=state['repairs'][rid];task=state['tasks'][repair['task_id']]
    assert state['stages'][task['stage_id']]['funding_stage_id']=='PKG'
    assert 'rlflow/policy.py' in state['stages'][task['stage_id']]['protected_paths']
    assert repairs.resource_stage(state,task['stage_id']) is state['stages']['PKG']
    from rlflow.packages import pause
    pause(h.store,'PKG',True)
    assert engine.dispatch_one(h.store) is None
    assert task['id'] not in h.store.replay()['autonomous_tasks']
    pause(h.store,'PKG',False)
    assert task['id'] in h.store.replay()['autonomous_tasks']
    stage=state['stages'][task['stage_id']]
    stage['module_roots']=['.']
    with pytest.raises(Conflict):repairs.validate_stage(state,stage)


def test_repair_does_not_expand_legacy_stage_authority(harness):
    h=harness;sid=engine.dispatch_one(h.store);se=h.store.replay()['sessions'][sid]
    h.store.transact('FIXTURE_INFRA','legacy-fail',lambda s:repairs.register_in(s,se,{'kind':'INFRASTRUCTURE'}))
    rid=next(iter(h.store.replay()['repairs']))
    assert not repairs.prepare(h.store,rid)
    assert len(h.store.replay()['tasks'])==1
