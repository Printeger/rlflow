"""Actual original approval persistence, never actual model consent or execution."""
import json

import pytest

from rlflow.hybrid_a_workflow_profile import PROFILE, registration, validate_spec
from rlflow.hybrid_authority import ApprovalService, SECTIONS
from rlflow.hybrid_goals import digest, propose
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Conflict, Store
from rlflow.observation import enable
from tests.test_hybrid_authority import setup, ORIGIN
from tests.test_hybrid_registry import catalog
from tests.test_hybrid_goal_v1_1 import explicit


def spec():
    return dict(profile=PROFILE,model='gpt-6.1-sol',
        account_mode='CHATGPT_CURRENT_WORKSPACE_ONLY',
        workspace_id='12345678-1234-1234-1234-123456789012',
        medium_sessions=6,high_sessions=2,session_seconds=300,
        input_tokens_soft=400000,output_tokens_soft=32000,
        wall_seconds=5400,controlled_seconds=3600,
        model_binary_sha256=digest('unqualified binary fixture'),
        model_gate_sha256=digest('unqualified gate fixture'),
        cpu_modules_sha256=digest('unqualified cpu fixture'),
        candidate_paths=['src/component.py','tests/component_test.py'],
        checks="print('checks passed')\n",cpu_seconds=30,
        cpu_limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12),
        cpu_acceptance=dict(method='EXACT_STDOUT_UTF8',stdout='checks passed\n',stderr_empty=True),
        repair_sessions=4,continuations=1,token_enforcement='SOFT_APPROVED',
        network_enforcement='PARTIAL_NOT_QUALIFIED',model_tools=False,
        api_billing=False,account_switch=False,gpu_enabled=False)


def workflow(value=None):
    value=spec() if value is None else value
    rows=registration(value); config=catalog()
    config.update(tools=rows['tools'],commands=rows['commands'],
        evaluation_rules={'workflow_rule':rows['rule']},resource_profile=rows['resources'])
    config['project_policy'].update(network_access='allowlist',allowed_hosts=['chatgpt.com'])
    registry=Registry(config); p=explicit()
    p.update(objective='Implement a task specified by the approved project contract',
        allowed_tools=['native_model','local_cpu'],registry_bindings=registry.bindings,
        stop_rules=['Unknown usage or incomplete scope STOP forbids new model sessions'],
        evaluation_data=dict(mode='EXPLICIT_NONE',datasets=[],
            evaluation_rule=dict(id='workflow_rule',version_hash=digest(rows['rule']))))
    p['scope'].update(allowed_command_templates=['native_model','local_cpu'],
        network_access='allowlist',allowed_hosts=['chatgpt.com'])
    p['budget'].update(model_sessions=value['medium_sessions']+value['high_sessions'],
        model_input_tokens=value['input_tokens_soft'],model_output_tokens=value['output_tokens_soft'],
        wall_seconds=value['wall_seconds'],model_token_enforcement='soft_approved')
    return registry,p


def test_actual_original_approval_and_cold_replay_pin_envelope_not_future_candidate(tmp_path):
    _,old,args,_,actor,_,utc=setup(tmp_path/'auth_fixture')
    store=Store(tmp_path/'workflow');enable(store,'project_fixture',data_mode='fixture')
    registry,p=workflow();p.update(goal_id='goal_workflow')
    propose(store,p,principal=actor,project_id=p['project_id'],data_mode='fixture',
        idempotency_key='workflow_draft',expected_revision=0)
    service=ApprovalService(store,old.auth,registry,project_id=p['project_id'],
        data_mode='fixture',origin=ORIGIN,clock=lambda:utc[0])
    confirmation=service.prepare(**args,goal_id=p['goal_id'],ttl_seconds=60)['confirmation']
    result=service.approve(confirmation,**args,idempotency_key='workflow_consent')
    assert result['execution_status']=='LEASE_VALIDATION_PENDING'
    fact=store.get(SECTIONS[0],result['fact_key'])
    assert fact['registry_witness']==json.loads(registry._raw)
    assert fact['registry_witness']['tools']['native_model']['definition']['spec']==spec()
    definition=fact['registry_witness']['tools']['native_model']['definition']
    assert definition['roles']['Engineer']['effort']=='medium'
    assert definition['roles']['Evaluator']['effort']=='high'
    assert not definition['execution_qualified']
    assert not any(field in definition['spec'] for field in ('packet_sha256','candidate_sha256'))
    assert not store.objects('sessions') and not store.objects('tasks')
    # This fixture authenticated consent is NOT permission to use the real account.
    store.snapshot()
    assert store.recover()==store.audit()==store.replay()


@pytest.mark.parametrize('change',['cpu_tool','review_schema','review_effort','policy',
    'budget','token_budget','gpu','protected_path','writable_path','cpu_network',
    'optional_review','optional_checks','protected_descendant'])
def test_rebound_invalid_envelope_refused_before_original_confirmation(tmp_path,change):
    _,old,args,_,actor,_,utc=setup(tmp_path/'auth_fixture');registry,p=workflow()
    store=Store(tmp_path/'workflow');enable(store,'project_fixture',data_mode='fixture')
    config=json.loads(registry._raw)
    if change=='cpu_tool':config['tools']['local_cpu']['adapter']='controlled_cpu'
    elif change in ('review_schema','review_effort','policy'):
        definition=config['tools']['native_model']['definition']
        if change=='review_schema':definition['roles']['Evaluator']['output_schema']={}
        elif change=='review_effort':definition['roles']['Evaluator']['effort']='medium'
        else:definition['policy']['continuations_max']=10
    elif change=='budget':p['budget']['model_sessions']=9
    elif change=='token_budget':p['budget']['model_input_tokens']=400001
    elif change=='gpu':p['budget']['gpu_device_seconds']=1
    elif change=='protected_path':p['scope']['protected_paths'].append('src/')
    elif change=='protected_descendant':p['scope']['protected_paths'].append('src/component.py/secret.py')
    elif change=='writable_path':p['scope']['writable_paths']=['tests/']
    elif change=='optional_review':p['global_conditions'][1]['required']=False
    elif change=='optional_checks':p['global_conditions'][0]['required']=False
    else:config['commands']['local_cpu'].update(network='allowlist',allowed_hosts=['chatgpt.com'])
    # Rebind hashes so failures exercise workflow semantics, not ordinary drift.
    registry=Registry(config);p['registry_bindings']=registry.bindings;p['goal_id']='bad_workflow'
    propose(store,p,principal=actor,project_id=p['project_id'],data_mode='fixture',
        idempotency_key='bad_workflow',expected_revision=0)
    service=ApprovalService(store,old.auth,registry,project_id=p['project_id'],
        data_mode='fixture',origin=ORIGIN,clock=lambda:utc[0])
    before=store.audit()
    with pytest.raises((Conflict,ProtocolError)):
        service.prepare(**args,goal_id=p['goal_id'],ttl_seconds=60)
    assert store.audit()==before and not store.objects(SECTIONS[0])


@pytest.mark.parametrize('change',['repair','high','bool','path','syntax','cpu_limit'])
def test_spec_is_closed_bounded_and_checks_are_not_executed(change):
    value=spec()
    if change=='repair':value['repair_sessions']=5
    elif change=='high':value['high_sessions']=1
    elif change=='bool':value['continuations']=True
    elif change=='path':value['candidate_paths']=['src/../protected.py']
    elif change=='syntax':value['checks']='def broken('
    else:value['cpu_limits']['cpu_max']='max 100000'
    with pytest.raises((Conflict,ProtocolError)):validate_spec(value)


def test_checks_are_only_compiled_and_outputs_are_detached():
    value=spec();value['checks']="raise RuntimeError('must never execute during approval')"
    rows=registration(value);rows['tools']['native_model']['definition']['spec']['checks']='changed'
    assert value['checks'].startswith('raise RuntimeError')
    assert rows['tools']['local_cpu']['definition']['spec']['checks']==value['checks']
    assert registration(value)['tools']['native_model']['definition']['spec']['checks']==value['checks']
