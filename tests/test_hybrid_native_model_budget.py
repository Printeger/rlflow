"""WIP generating ledger binding/math; NOT a live model/source qualification."""
from copy import deepcopy

import pytest

from rlflow.hybrid_budget import zero
from rlflow.hybrid_native_model_profile import (PROFILE, KIND, AUTHORIZATION,
    approved_binding, registration, validate_reservation)
from rlflow.hybrid_fixture_runtime_ledger import validate_runtime, ACTIONS, validate_original_links
from rlflow.hybrid_budget_ledger import SECTIONS, derived_heads
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict
from tests.test_hybrid_budget_ledger import ledger, heads
from tests.test_hybrid_admission import admission
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup

HASH='sha256:'+'a'*64


def _binding():
    spec=dict(profile=PROFILE,role='Engineer',model='gpt-6.1-sol',effort='medium',
        account_mode='CHATGPT_CURRENT_WORKSPACE_ONLY',workspace_id='12345678-1234-1234-1234-123456789012',
        packet_sha256=HASH,output_schema_sha256=HASH,candidate_sha256=HASH,binary_sha256=HASH,gate_sha256=HASH,
        model_input_tokens=1000,model_output_tokens=100,seconds=10,
        token_enforcement='SOFT_APPROVED',network_enforcement='PARTIAL_NOT_QUALIFIED',
        model_tools=False,api_billing=False,account_switch=False,gpu_enabled=False)
    rows=registration(spec)
    config=dict(tools={'native_model':rows['tool']},commands={'native_model':rows['command']},
        evaluation_rules={'native_model_rule':rows['rule']},resource_profile=rows['resources'])
    proposal=dict(goal_kind='engineering',allowed_tools=['native_model'],
        scope=dict(allowed_command_templates=['native_model'],network_access='allowlist',allowed_hosts=['chatgpt.com']),
        evaluation_data=dict(mode='EXPLICIT_NONE',datasets=[],
            evaluation_rule=dict(id='native_model_rule',version_hash=digest(rows['rule']))),
        budget={**zero(), 'model_sessions':8,'model_input_tokens':10000,'model_output_tokens':1000,
                'wall_seconds':600,'model_token_enforcement':'soft_approved'})
    binding=approved_binding(proposal,config,HASH)
    binding.update(grant_id='original_model_grant',proposal_hash=HASH,approval_hash=HASH,config_hash=HASH,scope_hash=HASH)
    return proposal,config,binding


def _runtime(binding):
    owner=dict(pid=1,pgid=1,starttime='1',boot_id='12345678-1234-1234-1234-123456789012')
    origin=dict(task_id='task',attempt_id='attempt',lease_id='lease',kind=KIND,authorization=AUTHORIZATION,
        program_sha256=HASH,scenario='native_model',native_model=binding,
        working_plan_intent=dict(key='intent',hash=HASH),working_plan_ready=dict(key='ready',hash=HASH),
        pool_claim=dict(key='claim',hash=HASH),pool_id='pool',member_id='member',owner=owner,nonce='a'*32,
        model_enabled=True,candidate_write_enabled=False,delegation_enabled=False)
    return dict(phase='REGISTER_NO_HANDOFF',origin=origin,registration=None,previous=None,
        producer=None,started_ack_sha256=None,terminal_proof_sha256=None,wall_seconds=0,
        native_model_handoff_attempted=False)


def test_generating_approval_and_reservation_cannot_borrow_zero_model_or_api_grant():
    proposal,config,binding=_binding()
    amount={**zero(),'model_sessions':1,'model_input_tokens':1000,'model_output_tokens':100,'wall_seconds':20}
    assert validate_reservation(amount,binding)==amount
    for name,value in [('model_sessions',0),('model_sessions',2),('model_input_tokens',0),
                       ('gpu_device_seconds',1),('experiment_starts',1)]:
        bad={**amount,name:value}
        with pytest.raises(Conflict):validate_reservation(bad,binding)
    for field,value in [('model_sessions',0),('model_input_tokens',0),('model_token_enforcement','hard_required')]:
        bad=deepcopy(proposal);bad['budget'][field]=value
        with pytest.raises(Conflict):approved_binding(bad,config,HASH)
    bad=deepcopy(config);bad['tools']['native_model']['definition']['spec']['api_billing']=True
    with pytest.raises(Conflict):approved_binding(proposal,bad,HASH)


@pytest.mark.parametrize('handoff,known_usage',[(False,False),(True,False),(True,True)],
    ids=['no_handoff','unknown_handoff','complete_format_math_only'])
def test_native_stopped_without_original_usage_never_settles_handoff_tokens(ledger,handoff,known_usage):
    _,_,binding=_binding();ledger=deepcopy(ledger)
    amount={**zero(),'model_sessions':1,'model_input_tokens':1000,'model_output_tokens':100,'wall_seconds':20}
    ledger['request']['amount']=amount;ledger['request_hash']=digest(ledger['request'])
    ledger['policy'].update(model_sessions=8,model_input_tokens=10000,model_output_tokens=1000,
                           wall_seconds=600,model_token_enforcement='soft_approved')
    runtime=_runtime(binding)
    def transition(phase,decision,reason):
        nonlocal ledger,runtime
        goal,reservation,project=heads(ledger)
        prior_runtime=reservation.get('fixture_runtime')
        runtime=deepcopy(runtime);runtime['phase']=phase
        if phase!='REGISTER_NO_HANDOFF':
            from rlflow.hybrid_budget_ledger import entry_key
            reference=dict(key=entry_key(ledger['request']),hash=digest(ledger))
            runtime['previous']=reference
            runtime['registration']=(prior_runtime['registration'] if prior_runtime and prior_runtime['registration']
                                     else reference)
        if phase=='HANDOFF_UNKNOWN':runtime['native_model_handoff_attempted']=True
        if phase=='PROCESS_REGISTERED':runtime['producer']={**runtime['origin']['owner'],
            'pid':2,'pgid':2,'starttime':'2'}
        if phase=='STARTED_AS_OBSERVED':runtime['started_ack_sha256']=HASH
        if phase=='FIXTURE_SCOPE_STOPPED':
            runtime['terminal_proof_sha256']=HASH
            if known_usage:
                from tests.test_hybrid_native_model_usage import publication
                runtime['wall_seconds']=21;runtime['native_model_usage']=publication(runtime)
        value=deepcopy(ledger)
        request={name:ledger['request'][name] for name in ('project_id','data_mode','goal_ref','store_epoch')}
        request.update(action='FIXTURE_RUNTIME_'+phase,idempotency_key=phase,
            expected_state_version=ledger['accepted_state_version'],reservation_id=reservation['reservation_id'],
            fixture_runtime=runtime)
        value.update(request=request,request_hash=digest(request),prior_goal=goal,prior_reservation=reservation,
            prior_project=project,accepted_state_version=ledger['accepted_state_version']+1,decision=decision,reason=reason)
        derived_heads(value);ledger=value
    transition('REGISTER_NO_HANDOFF','HELD','FIXTURE_REGISTERED_NO_HANDOFF')
    if handoff:transition('HANDOFF_UNKNOWN','UNKNOWN','FIXTURE_EXPOSURE_RETAINED')
    if known_usage:
        for phase in ('PROCESS_REGISTERED','RELEASE_INTENT','STARTED_AS_OBSERVED'):
            transition(phase,'UNKNOWN','FIXTURE_EXPOSURE_RETAINED')
    transition('STOP_REQUESTED','UNKNOWN','FIXTURE_EXPOSURE_RETAINED')
    transition('FIXTURE_SCOPE_STOPPED','UNKNOWN' if handoff and not known_usage else 'SETTLED',
        'NATIVE_MODEL_USAGE_SETTLED' if known_usage else
        'FIXTURE_EXPOSURE_RETAINED' if handoff else 'FIXTURE_SCOPE_TERMINATED')
    goal,reservation,project=heads(ledger)
    unresolved=handoff and not known_usage
    assert reservation['status']==('UNKNOWN' if unresolved else 'SETTLED')
    assert project['reserved']==(amount if unresolved else zero())
    assert project['unknown_exposure']==(amount if unresolved else zero())
    if known_usage:
        assert project['consumed']=={**zero(),'model_sessions':1,'model_input_tokens':12000,
            'model_output_tokens':1200,'wall_seconds':21}
        assert goal['balance']['model_input_tokens']['overrun']==2000
        assert goal['balance']['model_output_tokens']['overrun']==200
    else:assert project['consumed']==zero()
    if unresolved:
        forged=deepcopy(ledger);forged['decision']='SETTLED';forged['reason']='FIXTURE_SCOPE_TERMINATED'
        with pytest.raises(Conflict):derived_heads(forged)
        bad=deepcopy(ledger);bad['request']['fixture_runtime']['native_model_handoff_attempted']=False
        with pytest.raises(Conflict):derived_heads(bad)
    # No fake approval/source can be used as an original historical closure.
    with pytest.raises(Conflict,match='original approval missing'):
        validate_original_links(ledger,lambda section,key:None)


def test_generating_caller_json_never_reaches_original_runtime_writer(admission):
    from tests.test_hybrid_budget_service import actual
    owner,request,token = actual(admission)
    _,_,binding = _binding(); runtime = _runtime(binding)
    before = owner.store.audit()
    for action in ACTIONS:
        value = {**request, 'action': action, 'fixture_runtime': runtime,
                 'reservation_id': 'not_original'}
        with pytest.raises(PermissionError, match='no JSON runtime/refund'):
            owner.record(value, token)
    assert owner.store.audit() == before
