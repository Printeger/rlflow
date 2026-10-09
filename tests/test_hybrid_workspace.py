"""Pure workspace history over actual original preparation/budget fixtures.

No Workspace facts are persisted by these tests; domain is not Store authority.
"""
from copy import deepcopy
import json

import pytest

from rlflow import hybrid_workspace as module
from rlflow.hybrid_workspace import (SECTIONS,EVENT,fact_key,head_key,head,validate_record,
    validate_transition,validate_complete,expected_objects,claim_key,claim)
from rlflow.hybrid_budget_ledger import SECTIONS as BUDGET,reservation_key
from rlflow.hybrid_goals import digest
from rlflow.hybrid_preparation import source_binding
from rlflow.hybrid_working_copy import WorkingCopyOwner
from rlflow.store import Conflict
from tests.test_hybrid_budget_service import actual
from tests.test_hybrid_admission import admission
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def workspace(admission,tmp_path):
    budget,command,token=actual(admission);budget.record(command,token)
    prep=budget.preparation;namespace=tmp_path/'workspace-history';namespace.mkdir(mode=0o700)
    working=WorkingCopyOwner(prep.builder,namespace,clock=budget.controller.clock,
        monotonic_ns=budget.controller.monotonic_ns)
    base,_,_=prep._materials[command['preparation_intent_key']]
    observation=working.acquire(base)
    with prep.store.read_connection() as db:
        db.execute('BEGIN');sources=source_binding(prep._load(db,command['goal_ref']))
    reservation=prep.store.get(BUDGET[2],reservation_key(command))
    request={n:command[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    request.update({'idempotency_key':'workspace-acquire','expected_state_version':6,
        'expected_workspace_revision':0,'workspace_id':json.loads(observation.raw)['workspace_id'],
        'reservation_id':reservation['reservation_id'],'operation':'acquire','ttl_seconds':30})
    value={'request':request,'request_hash':digest(request),'sources':sources,'preparation':reservation['preparation'],
        'budget_reservation':reservation,'controller':admission[4]['controller'],'observation':json.loads(observation.raw),
        'observation_issued_monotonic_ns':observation.issued_monotonic_ns,
        'observation_expires_monotonic_ns':observation.expires_monotonic_ns,
        'controller_checked_monotonic_ns':100*10**9,'recorded_at':sources['evaluated_at'],
        'physical_close':None,
        'prior_head':None,'state':'HELD_PRE_RUNTIME','accepted_state_version':7,
        'execution_enabled':False,'release_enabled':False}
    try:yield prep,working,observation,value,prep.store.audit()
    finally:
        # A renewal replaces the actual current observation; clean that one,
        # never present historical JSON as a physical capability.
        for slot in tuple(working._issued.values()):working.close_pre_runtime(slot['observation'])


def transition(value,state,damage=None):
    request=value['request'];key=fact_key(request)
    payload={'format':2,'put':[[SECTIONS[0],key,value],[SECTIONS[1],head_key(request),head(value)]],
        'delete':[],'details':None}
    if request['operation']=='acquire':payload['put'].append([SECTIONS[2],claim_key(request),claim(value)])
    payload['put'].extend([[s,'',{}] for s in SECTIONS if s not in state])
    if damage:damage(payload)
    validate_transition(payload,lambda s,k:({} if s in state else None) if not k else state.get(s,{}).get(k),
        event_type=EVENT,key=key,object_id=request['reservation_id'],producer='hybrid-core',
        version=value['accepted_state_version'],registration=('project_fixture','fixture'))


def append(value,state):
    transition(value,state)
    state=deepcopy(state);state['version']=value['accepted_state_version']
    state.setdefault(SECTIONS[0],{})[fact_key(value['request'])]=value
    state.setdefault(SECTIONS[1],{})[head_key(value['request'])]=head(value)
    if value['request']['operation']=='acquire':state.setdefault(SECTIONS[2],{})[claim_key(value['request'])]=claim(value)
    return state


def complete(state,summary=None):
    proofs={k:((EVENT,'hybrid-core',v['request']['reservation_id'],v['accepted_state_version']),expected_objects(v))
        for k,v in state.get(SECTIONS[0],{}).items()}
    latest=max(state.get(SECTIONS[0],{}).items(),key=lambda item:item[1]['accepted_state_version'],default=None)
    if summary is None:summary=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(proofs))
    validate_complete(state,('project_fixture','fixture'),proofs.get,event_summary=summary)


def next_fact(previous,operation):
    value=deepcopy(previous);request=value['request'];request.update({'operation':operation,
        'idempotency_key':'workspace-'+operation,'expected_state_version':previous['accepted_state_version'],
        'expected_workspace_revision':previous['request']['expected_workspace_revision']+1})
    if operation in ('request_close','complete_close'):request.pop('ttl_seconds',None)
    value['request_hash']=digest(request);value['prior_head']=head(previous)
    value['accepted_state_version']+=1
    value['state']={'renew':'HELD_PRE_RUNTIME','request_close':'CLOSE_REQUESTED','complete_close':'CLOSED_PRE_RUNTIME'}[operation]
    if operation=='complete_close':
        # Closed DTO for pure schema/link checks only. No Store event or
        # physical capability is issued by constructing these JSON bytes.
        observation=value['observation'];value['physical_close']={'witness_id':'synthetic-close-dto',
            'workspace_id':request['workspace_id'],'observation_id':observation['observation_id'],
            'observation_hash':digest(observation),'kernel':observation['kernel'],
            'state':'CLOSED_PRE_RUNTIME','execution_enabled':False,'release_enabled':False}
    return value


def test_actual_origins_allow_only_historical_nonexecuting_fact(workspace):
    prep,_,_,value,state=workspace;before=prep.store.audit()
    validate_record(SECTIONS[0],fact_key(value['request']),value)
    complete(append(value,state))
    assert not value['execution_enabled'] and not value['release_enabled']
    assert prep.store.audit()==before and not prep.store.objects(SECTIONS[0])


def test_historical_close_requires_request_then_completion(workspace):
    _,_,_,value,state=workspace;state=append(value,state)
    requested=next_fact(value,'request_close');state=append(requested,state)
    closed=next_fact(requested,'complete_close');state=append(closed,state)
    complete(state)
    # Pure close facts do not themselves attest or close an actual descriptor.
    bad=next_fact(value,'complete_close')
    with pytest.raises(Conflict):transition(bad,state)


def test_renewal_matches_actual_same_hold_and_next_observation(workspace):
    _,working,observation,value,state=workspace;state=append(value,state)
    renewed=working.renew(observation);new=next_fact(value,'renew')
    new['observation']=json.loads(renewed.raw)
    new['observation_issued_monotonic_ns']=renewed.issued_monotonic_ns
    new['observation_expires_monotonic_ns']=renewed.expires_monotonic_ns
    new['sources']['source_version']=7
    complete(append(new,state))


@pytest.mark.parametrize('damage',['hash','version','revision','boolean','scope','budget_scope','cancelled',
    'runtime','budget_hash','prep_hash','base_id','base_hash','owner','controller_hash','controller_mono',
    'expired','ttl','mono_lifetime','mono_shift','initial_hash','output','release','execution','extra'])
def test_forged_binding_or_permission_upgrade_refused(workspace,damage):
    _,_,_,original,state=workspace;value=deepcopy(original)
    if damage=='hash':value['request_hash']=digest('wrong')
    elif damage=='version':value['accepted_state_version']+=1
    elif damage=='revision':value['request']['expected_workspace_revision']=1;value['request_hash']=digest(value['request'])
    elif damage=='boolean':value['observation_issued_monotonic_ns']=True
    elif damage=='scope':value['sources']['goal_ref']='wrong'
    elif damage=='budget_scope':value['budget_reservation']['scope']['goal_ref']='wrong'
    elif damage=='cancelled':value['budget_reservation']['status']='CANCELLED'
    elif damage=='runtime':value['budget_reservation']['runtime_registration']='REGISTERING'
    elif damage=='budget_hash':value['budget_reservation']['last_entry_hash']=digest('wrong')
    elif damage=='prep_hash':value['preparation']['intent_hash']=digest('wrong')
    elif damage=='base_id':value['observation']['base_snapshot_id']='wrong'
    elif damage=='base_hash':value['observation']['base_snapshot_hash']=digest('wrong')
    elif damage=='owner':value['observation']['kernel']['owner']['pid']+=1
    elif damage=='controller_hash':value['controller']['fact_hash']=digest('wrong')
    elif damage=='controller_mono':value['controller_checked_monotonic_ns']+=100*10**9
    elif damage=='expired':value['recorded_at']=value['observation']['expires_at']
    elif damage=='ttl':value['request']['ttl_seconds']=60;value['request_hash']=digest(value['request'])
    elif damage=='mono_lifetime':value['observation_expires_monotonic_ns']+=1
    elif damage=='mono_shift':
        value['observation_issued_monotonic_ns']+=100*10**9;value['observation_expires_monotonic_ns']+=100*10**9
    elif damage=='initial_hash':value['observation']['initial_copy_hash']=digest('not the copied original bytes')
    elif damage=='output':value['observation']['output_snapshot_hash']=digest('unattested output')
    elif damage in ('release','execution'):value[damage+'_enabled']=True
    else:value['unapproved']=True
    with pytest.raises((Conflict,ValueError)):transition(value,state)


@pytest.mark.parametrize('damage',['old_head','extra','duplicate','delete','marker','wrong_event','wrong_scope'])
def test_closed_event_shape_cannot_hide_mutation(workspace,damage):
    _,_,_,value,state=workspace
    def mutate(payload):
        if damage=='old_head':payload['put'][1][2]['revision']=2
        elif damage=='extra':payload['put'].append(['sessions','bad',{}])
        elif damage=='duplicate':payload['put'].append(payload['put'][0])
        elif damage=='delete':payload['delete'].append([SECTIONS[0],'bad'])
        elif damage=='marker':payload['put'][-1][2]={'bad':True}
        elif damage=='wrong_event':payload['details']={}
        else:payload['put'][1][1]='wrong'
    with pytest.raises((Conflict,ValueError)):transition(deepcopy(value),state,mutate)


@pytest.mark.parametrize('damage',['nonlatest','whole_domain','orphan','rollback'])
def test_historical_domain_tip_count_and_derived_heads_reject_omissions(workspace,damage):
    _,_,_,value,state=workspace;state=append(value,state)
    requested=next_fact(value,'request_close');state=append(requested,state)
    closed=next_fact(requested,'complete_close');state=append(closed,state)
    summary=((fact_key(closed['request']),closed['accepted_state_version']),3)
    if damage=='nonlatest':del state[SECTIONS[0]][fact_key(value['request'])]
    elif damage=='whole_domain':
        for s in SECTIONS:state.pop(s)
    elif damage=='orphan':state[SECTIONS[1]]['orphan']=head(closed)
    else:state[SECTIONS[1]][head_key(closed['request'])]=head(value)
    with pytest.raises((Conflict,ValueError)):complete(state,summary)


def test_cancelled_current_reservation_denies_new_work_but_not_history(workspace):
    _,_,_,value,state=workspace;historical=append(value,state)
    # Exact historical sources remain valid; projected current cancellation
    # must never be accepted for a new workspace or renewal.
    changed=deepcopy(state);changed[BUDGET[2]][value['request']['reservation_id']]['status']='CANCELLED'
    with pytest.raises(Conflict):transition(value,changed)
    complete(historical)


def test_same_actual_workspace_cannot_be_claimed_by_two_reservations(workspace):
    prep,_,_,original,_=workspace;budget=prep.store._hybrid_budget_service
    first=original['budget_reservation'];command=prep.store.get(BUDGET[0],first['origin_entry_key'])['request']
    command={**command,'idempotency_key':'second-reservation','expected_state_version':6}
    token=budget.controller._tokens[original['controller']['fact_key']]
    budget.record(command,token);state=prep.store.audit()
    value=deepcopy(original);value['request']['expected_state_version']=7;value['request_hash']=digest(value['request'])
    value['sources']['source_version']=7;value['accepted_state_version']=8;state=append(value,state)
    second=deepcopy(value);second['request'].update({'idempotency_key':'double-claim','expected_state_version':8,
        'reservation_id':reservation_key(command)})
    second['request_hash']=digest(second['request']);second['sources']['source_version']=8;second['accepted_state_version']=9
    second['budget_reservation']=prep.store.get(BUDGET[2],reservation_key(command))
    with pytest.raises(Conflict,match='already claimed'):transition(second,state)
    # Even a fully rehashed synthetic history cannot bind one actual workspace
    # id to another reservation by omitting the current-claim check.
    state[SECTIONS[0]][fact_key(second['request'])]=second
    state[SECTIONS[1]][head_key(second['request'])]=head(second);state['version']=9
    with pytest.raises(Conflict):complete(state)


def test_rehashed_original_budget_cannot_replace_preparation_consent(workspace):
    from rlflow.hybrid_budget_ledger import derived_heads
    _,_,_,original,state=workspace;state=deepcopy(state);value=deepcopy(original)
    key=value['budget_reservation']['last_entry_key'];entry=state[BUDGET[0]][key]
    entry['policy_source']['scope_hash']=digest('rehashed but wrong budget consent')
    state[BUDGET[2]][value['request']['reservation_id']]=derived_heads(entry)[BUDGET[2]][value['request']['reservation_id']]
    value['budget_reservation']=state[BUDGET[2]][value['request']['reservation_id']]
    with pytest.raises(Conflict):transition(value,state)
