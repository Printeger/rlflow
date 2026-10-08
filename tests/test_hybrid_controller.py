"""Historical controller facts must never become execution authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from rlflow.hybrid_controller import (SECTIONS, EVENT, fact_key, scope_key, head,
    validate_record, validate_transition, validate_complete)
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict

SCOPE=('project_fixture','fixture')
NOW=datetime(2026,10,9,tzinfo=timezone.utc)


def fact(previous=None, *, operation='acquire', delay=0, epoch='store_fixture',
         owner='owner_fixture', version=1):
    request={'authority_domain':'HYBRID_CORE_FACTS_ONLY','project_id':SCOPE[0],
        'data_mode':SCOPE[1],'store_epoch':epoch,
        'owner':{'id':owner,'process':{'pid':101,'pgid':101,'starttime':'1234','boot_id':'boot_fixture'}},
        'operation':operation,'idempotency_key':f'request_{version}','ttl_seconds':30,
        'expected_state_version':version-1,
        'expected_head_revision':0 if previous is None else previous['head_revision'],
        'previous_fact_key':None if previous is None else fact_key(previous['request']),
        'previous_fact_hash':None if previous is None else digest(previous)}
    now=NOW+timedelta(seconds=delay)
    reason='INITIAL' if previous is None else ('RENEWED' if operation=='renew' else
        ('NEW_STORE_EPOCH' if epoch!=previous['request']['store_epoch'] else 'EXPIRED_PREDECESSOR'))
    return {'request':request,'request_hash':digest(request),'config_hash':digest('config'),
        'controller_epoch':1 if previous is None else previous['controller_epoch']+(operation=='acquire'),
        'head_revision':request['expected_head_revision']+1,'issued_at':now.isoformat().replace('+00:00','Z'),
        'expires_at':(now+timedelta(seconds=30)).isoformat().replace('+00:00','Z'),
        'issued_monotonic_ns':(100+delay)*10**9,'expires_monotonic_ns':(130+delay)*10**9,
        'accepted_state_version':version,'reason':reason,'prior_runtime_recovery':'UNVERIFIED',
        'candidate_write_enabled':False,'execution_enabled':False}


def transition(state,value, *, damage=None):
    fk=fact_key(value['request']);hk=scope_key(*SCOPE)
    payload={'format':2,'put':[[SECTIONS[0],fk,value],[SECTIONS[1],hk,head(value)]],
             'delete':[],'details':None}
    for section in SECTIONS:
        if section not in state:payload['put'].append([section,'',{}])
    if damage:damage(payload)
    validate_transition(payload,lambda s,k:({} if s in state else None) if not k else state.get(s,{}).get(k),
        event_type=EVENT,key=fk,object_id=digest(value),producer='hybrid-core',
        version=value['accepted_state_version'],registration=SCOPE)


def state_of(*values):
    return {'version':max(v['accepted_state_version'] for v in values),
        SECTIONS[0]:{fact_key(v['request']):v for v in values},
        SECTIONS[1]:{scope_key(*SCOPE):head(values[-1])}}


def complete(state):
    proofs={k:((EVENT,'hybrid-core',digest(v),v['accepted_state_version']),
        sorted([(SECTIONS[0],k,digest(v)),(SECTIONS[1],scope_key(*SCOPE),digest(head(v)))]))
        for k,v in state.get(SECTIONS[0],{}).items()}
    latest=max(state.get(SECTIONS[0],{}).items(),key=lambda item:item[1]['accepted_state_version'],default=None)
    validate_complete(state,SCOPE,proofs.get,event_tip=None if latest is None else (latest[0],latest[1]['accepted_state_version']))


def test_initial_renew_expired_takeover_and_epoch_change_are_historical_only():
    initial=fact();transition({'version':0},initial)
    renewed=fact(initial,operation='renew',delay=10,version=2)
    transition(state_of(initial),renewed)
    acquired=fact(renewed,delay=40,owner='owner_other',version=3)
    transition(state_of(initial,renewed),acquired)
    changed=fact(acquired,delay=41,epoch='store_next',owner='owner_third',version=4)
    transition(state_of(initial,renewed,acquired),changed)
    complete(state_of(initial,renewed,acquired,changed))
    assert [v['controller_epoch'] for v in (initial,renewed,acquired,changed)]==[1,1,2,3]
    assert all(v['prior_runtime_recovery']=='UNVERIFIED' and not v['execution_enabled'] and
               not v['candidate_write_enabled'] for v in (initial,renewed,acquired,changed))


@pytest.mark.parametrize('damage',['hash','ttl','counter_bool','owner_bool','predecessor_pair',
    'initial_epoch','initial_operation','head_revision','scope','execution','candidate','extra'])
def test_invalid_initial_fact_refused(damage):
    value=fact()
    if damage=='hash':value['request_hash']=digest('other')
    elif damage=='ttl':value['expires_at']=value['issued_at']
    elif damage=='counter_bool':value['accepted_state_version']=True
    elif damage=='owner_bool':value['request']['owner']['process']['pid']=True
    elif damage=='predecessor_pair':value['request']['previous_fact_hash']=digest('missing')
    elif damage=='initial_epoch':value['controller_epoch']=2
    elif damage=='initial_operation':value['request']['operation']='renew'
    elif damage=='head_revision':value['head_revision']=2
    elif damage=='scope':value['request']['project_id']='project_other'
    elif damage=='execution':value['execution_enabled']=True
    elif damage=='candidate':value['candidate_write_enabled']=True
    else:value['unknown']={}
    if damage not in ('hash',):value['request_hash']=digest(value['request'])
    with pytest.raises(ValueError):transition({'version':0},value)


@pytest.mark.parametrize('damage',['expired','owner','process','epoch','config','controller_epoch',
    'reason','clock','source_hash','missing_source','stale_head'])
def test_renewal_requires_exact_unexpired_predecessor(damage):
    previous=fact();value=fact(previous,operation='renew',delay=10,version=2);state=state_of(previous)
    if damage=='expired':value=fact(previous,operation='renew',delay=30,version=2)
    elif damage=='owner':value['request']['owner']['id']='owner_other'
    elif damage=='process':value['request']['owner']['process']['starttime']='2345'
    elif damage=='epoch':value['request']['store_epoch']='store_other'
    elif damage=='config':value['config_hash']=digest('newconfig')
    elif damage=='controller_epoch':value['controller_epoch']=2
    elif damage=='reason':value['reason']='EXPIRED_PREDECESSOR'
    elif damage=='clock':value=fact(previous,operation='renew',delay=-1,version=2)
    elif damage=='source_hash':value['request']['previous_fact_hash']=digest('other')
    elif damage=='missing_source':state[SECTIONS[0]]={}
    else:state[SECTIONS[1]][scope_key(*SCOPE)]['revision']=2
    value['request_hash']=digest(value['request'])
    with pytest.raises(Conflict):transition(state,value)


@pytest.mark.parametrize('damage',['early','same_epoch','no_increment','wrong_reason','clock'])
def test_takeover_never_silently_extends_old_fence(damage):
    previous=fact();value=fact(previous,delay=30,owner='owner_other',version=2)
    if damage=='early':value=fact(previous,delay=29,owner='owner_other',version=2)
    elif damage=='same_epoch':value['controller_epoch']=1
    elif damage=='no_increment':value['controller_epoch']=3
    elif damage=='wrong_reason':value['reason']='NEW_STORE_EPOCH'
    else:value=fact(previous,delay=-1,epoch='store_other',version=2)
    with pytest.raises(Conflict):transition(state_of(previous),value)


@pytest.mark.parametrize('damage',['delete','extra_section','duplicate','missing_head','marker','format'])
def test_closed_two_object_transaction_required(damage):
    def corrupt(payload):
        if damage=='delete':payload['delete']=[[SECTIONS[1],scope_key(*SCOPE)]]
        elif damage=='extra_section':payload['put'].append(['sessions','unreleased',{}])
        elif damage=='duplicate':payload['put'].append(deepcopy(payload['put'][0]))
        elif damage=='missing_head':payload['put']=[r for r in payload['put'] if r[0]!=SECTIONS[1]]
        elif damage=='marker':payload['put'][-1][2]={'invented':True}
        else:payload['format']=1
    with pytest.raises(Conflict):transition({'version':0},fact(),damage=corrupt)


@pytest.mark.parametrize('damage',['head_delete','head_stale','fact_delete','fork','proof_missing','proof_digest'])
def test_history_derives_latest_head_and_original_event_pair(damage):
    initial=fact();renewed=fact(initial,operation='renew',delay=10,version=2)
    state=state_of(initial,renewed)
    if damage=='head_delete':state[SECTIONS[1]]={}
    elif damage=='head_stale':state[SECTIONS[1]][scope_key(*SCOPE)]=head(initial)
    elif damage=='fact_delete':del state[SECTIONS[0]][fact_key(initial['request'])]
    elif damage=='fork':
        other=fact(initial,operation='renew',delay=11,version=3)
        state['version']=3;state[SECTIONS[0]][fact_key(other['request'])]=other
    elif damage=='proof_missing':
        with pytest.raises(Conflict):validate_complete(state,SCOPE,lambda k:None)
        return
    else:
        with pytest.raises(Conflict):validate_complete(state,SCOPE,lambda k:((EVENT,'hybrid-core',digest('other'),1),[]))
        return
    with pytest.raises(Conflict):complete(state)


def test_idempotency_scope_excludes_operation_but_binds_actual_request():
    value=fact();changed=deepcopy(value['request']);changed['operation']='renew'
    assert fact_key(changed)==fact_key(value['request']) and digest(changed)!=value['request_hash']
    transition({'version':0},value)
    with pytest.raises(Conflict):transition(state_of(value),value)


def test_original_record_validation_is_io_free_after_expiry():
    value=fact();validate_record(SECTIONS[0],fact_key(value['request']),value)
    complete(state_of(value))


@pytest.mark.parametrize('damage',['clock_forward','boot_change','mono_bool','mono_ttl','initial_reset'])
def test_boot_bound_monotonic_deadline_and_no_reset(damage):
    previous=fact();value=fact(previous,delay=30,owner='owner_other',version=2);state=state_of(previous)
    if damage=='clock_forward':
        value['issued_monotonic_ns']=110*10**9;value['expires_monotonic_ns']=140*10**9
    elif damage=='boot_change':value['request']['owner']['process']['boot_id']='boot_other'
    elif damage=='mono_bool':value['issued_monotonic_ns']=True
    elif damage=='mono_ttl':value['expires_monotonic_ns']+=1
    else:
        value=fact();state={SECTIONS[0]:{},SECTIONS[1]:{},'version':0}
    value['request_hash']=digest(value['request'])
    with pytest.raises(ValueError):transition(state,value)
