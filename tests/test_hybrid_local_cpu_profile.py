"""Closed Core contract checks; these do not prove original live runtime grants."""
from copy import deepcopy

import pytest

from rlflow.hybrid_budget import zero
from rlflow.hybrid_fixture_runtime_ledger import validate_runtime, ACTIONS
from rlflow.hybrid_local_cpu_profile import (PROFILE, KIND, AUTHORIZATION, MODULES,
        registration, approved_binding, validate_spec)
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict

HASH='sha256:'+'a'*64


def approved_sources(purpose='research'):
    spec=dict(purpose=purpose,code="import json; print(json.dumps({'sample_count':len([3,5,9])}))",
              inputs={'parameters.json':'{"threshold": 2}'},seconds=10,
              limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
    pins=dict.fromkeys(MODULES,HASH)
    registered=registration(spec,pins)
    config=dict(tools={'local_cpu':registered['tool']},commands={'local_cpu':registered['command']},
                evaluation_rules={'local_cpu_rule':registered['rule']},resource_profile=registered['resources'])
    proposal=dict(goal_kind=purpose,risk='low',allowed_tools=['local_cpu'],
        scope=dict(allowed_command_templates=['local_cpu'],network_access='none',allowed_hosts=[]),
        evaluation_data=dict(mode='EXPLICIT_NONE',datasets=[],
            evaluation_rule=dict(id='local_cpu_rule',version_hash=digest(registered['rule']))),
        budget=dict(model_sessions=0,model_input_tokens=0,model_output_tokens=0,
                    gpu_device_seconds=0,experiment_retries=0,experiment_starts=int(purpose=='research'),wall_seconds=20))
    return proposal,config,spec


def registration_request(purpose='research'):
    proposal,config,spec=approved_sources(purpose)
    binding=approved_binding(proposal,config,HASH)
    binding.update(grant_id='original_grant',proposal_hash=HASH,approval_hash=HASH,config_hash=HASH,scope_hash=HASH)
    process=dict(pid=1,pgid=1,starttime='1',boot_id='12345678-1234-1234-1234-123456789012')
    origin=dict(task_id='task',attempt_id='attempt',lease_id='lease',kind=KIND,authorization=AUTHORIZATION,
                program_sha256=HASH,scenario='local_cpu',local_cpu=binding,
                working_plan_intent=dict(key='intent',hash=HASH),working_plan_ready=dict(key='ready',hash=HASH),
                pool_claim=dict(key='claim',hash=HASH),pool_id='pool',member_id='member',owner=process,
                nonce='a'*32,model_enabled=False,candidate_write_enabled=False,delegation_enabled=False)
    runtime=dict(phase='REGISTER_NO_HANDOFF',origin=origin,registration=None,previous=None,
                 producer=None,started_ack_sha256=None,terminal_proof_sha256=None,wall_seconds=0,
                 local_cpu_release_attempted=False)
    request=dict(action=ACTIONS[0],data_mode='fixture',fixture_runtime=runtime)
    prior=dict(status='HELD',runtime_registration='NOT_AUTHORIZED',amount={**zero(),
                'wall_seconds':20,'experiment_starts':int(purpose=='research')})
    return request,prior


def test_frozen_configured_source_binding_and_budget_registration():
    proposal,config,spec=approved_sources()
    binding=approved_binding(proposal,config,HASH)
    assert binding['profile']==PROFILE and binding['inputs_sha256']==digest(spec['inputs'])
    request,prior=registration_request()
    assert validate_runtime(request,prior)==request['fixture_runtime']
    request['fixture_runtime']['origin']['local_cpu']['purpose']='engineering'
    with pytest.raises(Conflict,match='reservation'):validate_runtime(request,prior)


def test_configured_acceptance_is_frozen_bounded_and_not_implicit_success():
    from rlflow.hybrid_local_cpu_profile import evaluate_output,validate_bound_spec
    proposal,config,spec=approved_sources()
    output={'stdout':{'text':'configured measurement\n'},'stderr':{'text':''}}
    assert evaluate_output(spec,output)['status']=='NOT_CONFIGURED'
    spec['acceptance']={'method':'EXACT_STDOUT_UTF8','stdout':'configured measurement\n','stderr_empty':True}
    assert evaluate_output(spec,output)['status']=='PASS'
    output['stdout']['text']='wrong measurement\n'
    assert evaluate_output(spec,output)['status']=='FAIL'
    binding={'spec_sha256':digest(spec),'inputs_sha256':digest(spec['inputs']),
        'code_sha256':__import__('hashlib').sha256(spec['code'].encode()).hexdigest(),
        'purpose':spec['purpose'],'task_seconds':spec['seconds']}
    binding['code_sha256']='sha256:'+binding['code_sha256']
    assert validate_bound_spec(spec,binding)==spec
    spec['acceptance']['stdout']='laundered measurement\n'
    with pytest.raises(Conflict,match='approved grant'):validate_bound_spec(spec,binding)
    spec['acceptance']['stderr_empty']=1
    with pytest.raises(Conflict,match='acceptance'):validate_spec(spec)


@pytest.mark.parametrize('change',['code','inputs','modules','model','wall','old_tool'])
def test_fresh_approval_cannot_launder_changed_or_fixed_profile(change):
    proposal,config,spec=approved_sources()
    if change in ('code','inputs','modules'):
        changed=config['tools']['local_cpu']['definition']
        if change=='modules':changed['modules'][MODULES[0]]='sha256:'+'b'*64
        elif change=='code':changed['spec']['code']='print("changed after approval")'
        else:changed['spec']['inputs']['parameters.json']='{"threshold": 999}'
    elif change=='model':proposal['budget']['model_sessions']=1
    elif change=='wall':proposal['budget']['wall_seconds']=19
    else:proposal['allowed_tools']=['cpu_trial']
    with pytest.raises(Conflict):approved_binding(proposal,config,HASH)


@pytest.mark.parametrize('change',['bool_seconds','path','oversize','unlimited_cpu','missing_pids'])
def test_private_input_and_resource_bounds_fail_closed(change):
    _,_,spec=approved_sources()
    if change=='bool_seconds':spec['seconds']=True
    elif change=='path':spec['inputs']['../controller']='outside'
    elif change=='oversize':spec['inputs']['huge']='x'*65537
    elif change=='unlimited_cpu':spec['limits']['cpu_max']='max 100000'
    else:del spec['limits']['pids_max']
    with pytest.raises(Conflict):validate_spec(spec)


def test_fixed_origin_cannot_acquire_local_release_and_local_cannot_forge_started():
    request,prior=registration_request()
    request['fixture_runtime']['local_cpu_release_attempted']=True
    with pytest.raises(Conflict,match='release'):validate_runtime(request,prior)
    request['fixture_runtime']['local_cpu_release_attempted']=False
    origin=request['fixture_runtime']['origin']
    del origin['local_cpu']
    origin.update(kind='PROTOCOL_CONFORMANCE',authorization='LOCAL_PROTOCOL_ONLY',scenario='complete')
    with pytest.raises(Conflict,match='fixed capability'):validate_runtime(request,prior)


def test_stop_cannot_create_a_release_attempt_from_no_handoff():
    request,prior=registration_request()
    old=deepcopy(request['fixture_runtime'])
    prior.update(fixture_runtime=old,last_entry_key='registration',last_entry_hash=HASH)
    request['action']=ACTIONS[-2]
    value=request['fixture_runtime']
    value.update(phase='STOP_REQUESTED',registration=dict(key='registration',hash=HASH),
                 previous=dict(key='registration',hash=HASH),local_cpu_release_attempted=True)
    with pytest.raises(Conflict,match='release'):validate_runtime(request,prior)


@pytest.mark.parametrize('purpose,released', [('research',False),('research',True),('engineering',True)])
def test_configurable_cpu_budget_conserves_exposure_and_charges_one_g_attempt(purpose,released):
    # Pure derivation only. Synthetic source/producer DTOs do NOT authorize Store
    # writes, prove live approval, launch a worker or establish manager terminal.
    from rlflow.hybrid_budget_ledger import derived_heads, SECTIONS
    initial,prior=registration_request(purpose)
    scope=dict(project_id='project',data_mode='fixture',goal_ref='goal',store_epoch='epoch')
    entry=dict(request={**scope,'idempotency_key':'reserve','action':'RESERVE',
                'amount':prior['amount'],'purpose':'EXECUTION'},
               policy={**zero(),'wall_seconds':100,'experiment_starts':3,
                       'model_token_enforcement':'hard_required','finalization_reserve_fraction':0.2},
               policy_source={'synthetic_arithmetic_only':True},preparation={'synthetic_arithmetic_only':True},
               prior_goal=None,prior_reservation=None,prior_project=None,
               decision='HELD',reason='BUDGET_RESERVED',accepted_state_version=1)
    runtime=deepcopy(initial['fixture_runtime'])
    phases=[0,1,2,3,5,6] if released else [0,5,6]
    for index in phases:
        derived=derived_heads(entry)
        goal,reservation,project=(next(iter(derived[section].values())) for section in SECTIONS[1:])
        reference=dict(key=reservation['last_entry_key'],hash=reservation['last_entry_hash'])
        runtime.update(phase=ACTIONS[index].removeprefix('FIXTURE_RUNTIME_'),
                       previous=None if index==0 else reference)
        if index==1:runtime['registration']=reference
        if index==5 and runtime['registration'] is None:runtime['registration']=reference
        if index==2:runtime['producer']=deepcopy(runtime['origin']['owner'])
        if index>=5:runtime['local_cpu_release_attempted']=released
        if index==6:runtime.update(terminal_proof_sha256=HASH,wall_seconds=1)
        entry=dict(request={**scope,'idempotency_key':'phase_'+str(index),'action':ACTIONS[index],
                    'reservation_id':reservation['reservation_id'],'fixture_runtime':deepcopy(runtime)},
                   policy=entry['policy'],policy_source=entry['policy_source'],preparation=entry['preparation'],
                   prior_goal=goal,prior_reservation=reservation,prior_project=project,
                   decision='HELD' if index==0 else 'SETTLED' if index==6 else 'UNKNOWN',
                   reason='FIXTURE_REGISTERED_NO_HANDOFF' if index==0 else
                          'FIXTURE_SCOPE_TERMINATED' if index==6 else 'FIXTURE_EXPOSURE_RETAINED',
                   accepted_state_version=entry['accepted_state_version']+1)
        current=derived_heads(entry)
        project=next(iter(current[SECTIONS[3]].values()))
        if index in (1,2,3,5):
            assert project['reserved']==project['unknown_exposure']==prior['amount']
    assert project['consumed']['experiment_starts']==int(purpose=='research' and released)
    assert project['consumed']['wall_seconds']==1
    assert project['reserved']==project['unknown_exposure']==zero()
