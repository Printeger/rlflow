"""Approved next-demand gates; these pure tests grant no runtime authority."""
import copy
import json

import pytest

from rlflow.hybrid_a_workflow_continuation import from_acceptance
from rlflow.hybrid_a_workflow_profile import validate_spec
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Conflict
from tests.test_hybrid_a_workflow_profile import workflow,spec


def test_unused_continuation_quota_is_not_a_task():
    registry,proposal=workflow()
    assert spec()['continuations']==1
    with pytest.raises(Conflict,match='no explicitly approved continuation demand'):
        from_acceptance(proposal,json.loads(registry._raw),None,{})


@pytest.mark.parametrize('damage',['empty','blank','unknown','unicode_bytes','bad_id'])
def test_bounded_closed_next_task(damage):
    value=spec();task={'task_id':'next_task','objective':'Implement the separately approved next task'}
    if damage=='empty':task['objective']=''
    elif damage=='blank':task['objective']='   '
    elif damage=='unknown':task['extra']='no'
    elif damage=='unicode_bytes':task['objective']='续'*1400
    else:task['task_id']='bad id'
    value['continuation_task']=task
    with pytest.raises((Conflict,ProtocolError)):validate_spec(value)


def test_demand_changes_entire_approved_config_and_rule_not_previous_approval():
    from rlflow.hybrid_a_workflow_profile import registration,validate_approval
    from rlflow.hybrid_goals import digest
    registry,proposal=workflow();value=spec()
    value['continuation_task']={'task_id':'next_task','objective':'Implement a different approved task'}
    rows=registration(value);config=json.loads(registry._raw)
    config.update(tools=rows['tools'],commands=rows['commands'],evaluation_rules={'workflow_rule':rows['rule']},resource_profile=rows['resources'])
    assert digest(config)!=registry.config_hash
    with pytest.raises((Conflict,ProtocolError)):validate_approval(copy.deepcopy(proposal),config)


def continuation_entry():
    from tests.test_hybrid_native_model_budget import _binding,_runtime,HASH
    from tests.test_hybrid_a_workflow_accounting import entry,advance
    value=entry();prior=advance(value,None)
    prior.update(candidate_cpu_entry='cpu_register',review_entries={'cpu_register':'review_register'},
        high_sessions=1,controlled_seconds_charged=660)
    _,_,binding=_binding()
    binding['workflow']={**value['request']['fixture_runtime']['origin']['native_model']['workflow'],
        'profile':'A_ENGINEERING_WORKFLOW_V2','stage':'CONTINUATION','task_id':'next_task',
        'intent':{'key':'intent','hash':HASH},'ready':{'key':'ready','hash':HASH},
        'files':{'module/source.py':'accepted candidate'},
        'parents':{name:{'key':name,'hash':HASH} for name in ('engineer','cpu','reviewer')},
        'acceptance':{'key':'accepted','hash':HASH}}
    value['request']['fixture_runtime']=_runtime(binding)
    value['prior_reservation']['amount']['wall_seconds']=20
    return value,prior


def test_continuation_charges_exactly_once_without_resetting_history():
    from rlflow.hybrid_a_workflow_accounting import advance
    value,prior=continuation_entry();head=advance(value,prior)
    assert head['medium_sessions']==2 and head['high_sessions']==1
    assert head['controlled_seconds_charged']==680
    for key in ('started_at','first_engineer_entry','candidate_cpu_entry','review_entries'):
        assert head[key]==prior[key]
    with pytest.raises(Conflict,match='unique accepted continuation'):advance(value,head)
    later=copy.deepcopy(value);later['request']['fixture_runtime']['phase']='FIXTURE_SCOPE_STOPPED'
    assert advance(later,head)==head


@pytest.mark.parametrize('damage',['no_review','medium','seconds','short_charge','cross_approval','schema_spill'])
def test_continuation_gate_rejects_exhausted_or_wrong_stage(damage):
    from rlflow.hybrid_a_workflow_accounting import advance
    value,prior=continuation_entry()
    if damage=='no_review':prior.pop('review_entries')
    elif damage=='medium':prior['medium_sessions']=6
    elif damage=='seconds':prior['controlled_seconds_charged']=3599
    elif damage=='short_charge':value['prior_reservation']['amount']['wall_seconds']=19
    elif damage=='cross_approval':prior['approval_sha256']='sha256:'+'b'*64
    else:value['request']['fixture_runtime']['origin']['native_model']['workflow']['cpu_registration']='cpu_register'
    with pytest.raises((Conflict,ProtocolError)):advance(value,prior)
