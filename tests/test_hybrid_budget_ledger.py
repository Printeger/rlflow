"""Closed local budget derivation from actual fixture data; not Store admission."""
from copy import deepcopy

import pytest

from rlflow.hybrid_budget import zero,account_key
from rlflow.hybrid_budget_ledger import (SECTIONS,entry_key,reservation_key,project_key,
    EVENT,scope,derived_heads,validate_record,validate_transition,validate_complete,expected_objects)
from rlflow.hybrid_goals import SECTIONS as GOALS,digest
from rlflow.store import Conflict
from tests.test_hybrid_admission import admission
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def ledger(admission):
    prep,_,_,_,original,state=admission;source=deepcopy(original['sources'])
    policy=deepcopy(state[GOALS[0]][source['contract_key']]['contract']['proposal']['budget'])
    request={'project_id':prep.project_id,'data_mode':prep.data_mode,'goal_ref':source['goal_ref'],
        'store_epoch':prep.store_epoch,'idempotency_key':'reserve-original','expected_state_version':5,
        'action':'RESERVE','preparation_intent_key':original['preparation']['intent_key'],
        'amount':{**zero(),'wall_seconds':1},'purpose':'EXECUTION'}
    entry={'schema_version':'1.0','request':request,'request_hash':digest(request),
        'policy_source':source,'policy':policy,'preparation':original['preparation'],
        'controller':original['controller'],'recorded_at':source['evaluated_at'],
        'controller_checked_monotonic_ns':original['controller_checked_monotonic_ns'],
        'prior_goal':None,'prior_reservation':None,'prior_project':None,
        'decision':'HELD','reason':'BUDGET_RESERVED','accepted_state_version':6,'execution_enabled':False}
    return entry


def heads(entry):
    result=derived_heads(entry)
    return tuple(next(iter(result[s].values())) for s in SECTIONS[1:])


def follow(entry,action,key='next'):
    goal,reservation,project=heads(entry);value=deepcopy(entry)
    request={k:entry['request'][k] for k in ('project_id','data_mode','goal_ref','store_epoch')}
    request.update(action=action,idempotency_key=key,expected_state_version=entry['accepted_state_version'],
                   reservation_id=reservation['reservation_id'])
    value.update(request=request,request_hash=digest(request),prior_goal=goal,
        prior_reservation=reservation,prior_project=project,accepted_state_version=entry['accepted_state_version']+1,
        decision='UNKNOWN' if action=='MARK_UNKNOWN' else 'CANCELLED',
        reason='EXPOSURE_UNKNOWN' if action=='MARK_UNKNOWN' else 'CORE_CANCELLED_BEFORE_RUNTIME')
    return value


def test_actual_fixture_values_derive_closed_nonexecuting_budget_heads(ledger):
    validate_record(SECTIONS[0],entry_key(ledger['request']),ledger)
    for section,values in derived_heads(ledger).items():
        for key,value in values.items():validate_record(section,key,value)
    goal,reservation,project=heads(ledger)
    assert goal['balance']['wall_seconds']['reserved']==1
    assert reservation['status']=='HELD' and reservation['execution_enabled'] is False
    assert project['reserved']['wall_seconds']==1
    assert project['unknown_exposure']['wall_seconds']==0


def test_denied_reservation_retains_every_exposure(ledger):
    value=deepcopy(ledger)
    value['request']['amount']['wall_seconds']=value['policy']['wall_seconds']+1
    value['request_hash']=digest(value['request']);value.update(decision='DENIED',reason='BUDGET_UNAVAILABLE')
    validate_record(SECTIONS[0],entry_key(value['request']),value)
    goal,reservation,project=heads(value)
    assert reservation['status']=='DENIED'
    assert goal['balance']['wall_seconds']['reserved']==0 and project['reserved']==zero()
    with pytest.raises(Conflict):derived_heads(follow(value,'CANCEL_BEFORE_RUNTIME'))


def test_unknown_is_retained_not_second_charge_or_cancel_permission(ledger):
    value=follow(ledger,'MARK_UNKNOWN');validate_record(SECTIONS[0],entry_key(value['request']),value)
    goal,reservation,project=heads(value)
    assert reservation['status']=='UNKNOWN'
    assert goal['balance']['wall_seconds']['reserved']==goal['balance']['wall_seconds']['unknown_exposure']==1
    assert project['reserved']['wall_seconds']==project['unknown_exposure']['wall_seconds']==1
    for action in ('MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'):
        with pytest.raises(Conflict):derived_heads(follow(value,action))


def test_held_cancel_is_terminal_and_does_not_change_consumed(ledger):
    value=follow(ledger,'CANCEL_BEFORE_RUNTIME');validate_record(SECTIONS[0],entry_key(value['request']),value)
    goal,reservation,project=heads(value)
    assert reservation['status']=='CANCELLED' and reservation['runtime_registration']=='NOT_AUTHORIZED'
    assert goal['balance']['wall_seconds']['consumed']==0 and project['reserved']==zero()
    for action in ('MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'):
        with pytest.raises(Conflict):derived_heads(follow(value,action))


@pytest.mark.parametrize('damage',['hash','decision','reason','version','scope','amount_bool','purpose',
                                 'extra','release','runtime_phase','reservation_id','policy_change'])
def test_closed_derivation_rejects_local_forgery(ledger,damage):
    value=follow(ledger,'CANCEL_BEFORE_RUNTIME') if damage in ('runtime_phase','reservation_id','policy_change') else deepcopy(ledger)
    if damage=='hash':value['request_hash']=digest('different')
    elif damage=='decision':value['decision']='DENIED'
    elif damage=='reason':value['reason']='BUDGET_UNAVAILABLE'
    elif damage=='version':value['accepted_state_version']=7
    elif damage=='scope':value['prior_goal']=heads(ledger)[0];value['prior_goal']['scope']['goal_ref']='other'
    elif damage=='amount_bool':value['request']['amount']['wall_seconds']=True
    elif damage=='purpose':value['request']['purpose']='FINAL_VALIDATION'
    elif damage=='extra':value['usage']={'state':'USED'}
    elif damage=='release':value['execution_enabled']=True
    elif damage=='runtime_phase':value['prior_reservation']['runtime_registration']='REGISTERED'
    elif damage=='reservation_id':value['request']['reservation_id']='other';value['request_hash']=digest(value['request'])
    else:value['policy']['wall_seconds']+=1
    with pytest.raises(ValueError):validate_record(SECTIONS[0],entry_key(value['request']),value)


def test_goal_head_limits_must_match_its_original_policy(ledger):
    value=heads(ledger)[0];value=deepcopy(value)
    value['balance']['wall_seconds']['limit']+=1
    value['balance']['wall_seconds']['available']+=1
    with pytest.raises(Conflict,match='limits differ'):
        validate_record(SECTIONS[1],account_key(value['scope']),value)


def append(entry,state):
    key=entry_key(entry['request']);derived=derived_heads(entry)
    payload={'format':2,'put':[[SECTIONS[0],key,entry]],'delete':[],'details':None}
    payload['put'].extend([s,k,v] for s,values in derived.items() for k,v in values.items())
    payload['put'].extend([s,'',{}] for s in SECTIONS if s not in state)
    validate_transition(payload,lambda s,k:({} if s in state else None) if not k else state.get(s,{}).get(k),
        event_type=EVENT,key=key,object_id=account_key(scope(entry['request'])),producer='hybrid-core',
        version=entry['accepted_state_version'],registration=('project_fixture','fixture'))
    result=deepcopy(state);result['version']=entry['accepted_state_version']
    result.setdefault(SECTIONS[0],{})[key]=entry
    for section,values in derived.items():result.setdefault(section,{}).update(values)
    return result


def complete(state,summary=None):
    entries=state.get(SECTIONS[0],{})
    proofs={k:((EVENT,'hybrid-core',account_key(scope(v['request'])),v['accepted_state_version']),expected_objects(v))
            for k,v in entries.items()}
    latest=max(entries.items(),key=lambda item:item[1]['accepted_state_version'],default=None)
    if summary is None:summary=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(entries))
    validate_complete(state,('project_fixture','fixture'),proofs.get,event_summary=summary)


@pytest.mark.parametrize('action',['MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'])
def test_original_fixture_links_transition_and_full_history(ledger,admission,action):
    before=admission[0].store.audit();state=append(ledger,admission[-1]);complete(state)
    state=append(follow(ledger,action),state);complete(state)
    assert admission[0].store.audit()==before  # Pure, not actual ledger persistence.


@pytest.mark.parametrize('damage',['whole_domain','nonlatest','extra_head','changed_head'])
def test_full_reconstruction_rejects_omissions_and_orphan_heads(ledger,admission,damage):
    first=append(ledger,admission[-1]);second=follow(ledger,'MARK_UNKNOWN')
    state=append(second,first);summary=((entry_key(second['request']),7),2)
    complete(state,summary);state=deepcopy(state)
    if damage=='whole_domain':
        for section in SECTIONS:state.pop(section)
    elif damage=='nonlatest':del state[SECTIONS[0]][entry_key(ledger['request'])]
    elif damage=='extra_head':state[SECTIONS[2]]['orphan']=heads(second)[1]
    else:
        goal=next(iter(state[SECTIONS[1]].values()))
        goal['balance']['wall_seconds']['unknown_exposure']=0
    with pytest.raises(ValueError):complete(state,summary)


@pytest.mark.parametrize('damage',['policy','controller','preparation','source_version','scope','capture'])
def test_historical_dependencies_cannot_be_changed_even_with_new_hash(ledger,admission,damage):
    value=deepcopy(ledger)
    if damage=='policy':value['policy']['wall_seconds']+=1
    elif damage=='controller':value['controller']['fact_hash']=digest('forged')
    elif damage=='preparation':value['preparation']['intent_hash']=digest('forged')
    elif damage=='source_version':value['policy_source']['source_version']=4
    elif damage=='scope':value['policy_source']['goal_ref']='foreign'
    else:value['controller_checked_monotonic_ns']+=30*10**9
    with pytest.raises(ValueError):append(value,admission[-1])


def test_cleanup_does_not_require_current_goal_or_approval_heads(ledger,admission):
    from rlflow.hybrid_authority import SECTIONS as AUTHORITY
    state=append(ledger,admission[-1]);state[GOALS[1]]={};state[AUTHORITY[2]]={}
    state=append(follow(ledger,'MARK_UNKNOWN'),state);complete(state)


def test_actual_generated_budget_indexes_have_exact_required_ddl(admission):
    store=admission[0].store
    with store.read_connection() as db:store._require_budget_indices(db)


@pytest.mark.parametrize('path',['$.BUDGET_RESERVATION_ID','$.budget_ reservation_id'])
def test_wrong_json_path_index_is_not_normalized_into_permission(admission,path):
    store=admission[0].store
    with store.connect() as db:
        db.execute('DROP INDEX events_budget_reservation_tip')
        db.execute("CREATE INDEX events_budget_reservation_tip ON events(event_type,CASE WHEN json_valid(input_versions) THEN json_extract(input_versions,'"+path+"') END,seq DESC)")
    with store.read_connection() as db:
        with pytest.raises(Conflict,match='explicit schema upgrade'):store._require_budget_indices(db)


def test_readonly_attach_does_not_upgrade_missing_budget_index(admission):
    from rlflow.store import Store
    store=admission[0].store
    with store.connect() as db:db.execute('DROP INDEX events_budget_reservation_tip')
    store.root.chmod(0o700)
    (store.root/'runtime').chmod(0o700)
    store.db.chmod(0o600)
    (store.root/'runtime/writer.lock').chmod(0o600)
    readonly=Store.attach_existing(store.root,project_id=admission[0].project_id,data_mode=admission[0].data_mode)
    with readonly.read_connection() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='events_budget_reservation_tip'").fetchone() is None
        with pytest.raises(Conflict,match='explicit schema upgrade'):readonly._require_budget_indices(db)
