"""Pure BLOCKED facts from actual approved/prepared/controller fixture sources."""
from copy import deepcopy
import json

import pytest

from rlflow.hybrid_admission import (SECTION,EVENT,fact_key,gates,validate_record,
    validate_transition,validate_complete)
from rlflow.hybrid_controller_service import ControllerService
from rlflow.hybrid_controller import fact_key as controller_key
from rlflow.hybrid_preparation import source_binding,intent_key,result_key
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def admission(owned):
    prep,request,clock,_=owned;prepared=prep.prepare(request);mono=[100*10**9]
    prep._witness_monotonic_ns=lambda:mono[0]
    control=ControllerService(prep.store,prep.registry,project_id=prep.project_id,data_mode=prep.data_mode,
        store_epoch=prep.store_epoch,clock=lambda:clock[0],monotonic_ns=lambda:mono[0])
    acquired=control.acquire('actual-controller',expected_version=4);witness=prep.issue_material_witness(intent_key(request))
    with prep.store.read_connection() as db:
        db.execute('BEGIN');sources=source_binding(prep._load(db,request['goal_ref']))
    req={'idempotency_key':'actual-admission','project_id':prep.project_id,'data_mode':prep.data_mode,
         'store_epoch':prep.store_epoch,'preparation_intent_key':intent_key(request),'expected_state_version':5}
    value={'schema_version':'1.0','request':req,'request_hash':digest(req),
        'preparation':{'intent_key':intent_key(request),'intent_hash':digest(prepared['intent']),
            'result_key':result_key(intent_key(request)),'result_hash':digest(prepared['result'])},
        'controller':{'fact_key':controller_key(acquired['fact']['request']),'fact_hash':digest(acquired['fact']),
            'controller_epoch':1,'head_revision':1},'material_observation':json.loads(witness.raw),
        'material_observation_monotonic':{'boot_id':witness.boot_id,
            'issued_ns':witness.issued_monotonic_ns,'expires_ns':witness.expires_monotonic_ns},
        'sources':sources,'recorded_at':sources['evaluated_at'],'controller_checked_monotonic_ns':mono[0],
        'accepted_state_version':6,'status':'BLOCKED','reason':'EXECUTION_GATES_UNVERIFIED','gates':gates(),
        'candidate_write_enabled':False,'release_enabled':False,'execution_enabled':False}
    # The fixture is the actual token's caller. Keep its frame/acquired token
    # alive until teardown; the production weak cache must not retain or adopt it.
    yield prep,control,prepared,witness,value,prep.store.replay()


def transition(value,state,damage=None):
    key=fact_key(value['request']);payload={'format':2,'put':[[SECTION,key,value]],'delete':[],'details':None}
    if SECTION not in state:payload['put'].append([SECTION,'',{}])
    if damage:damage(payload)
    validate_transition(payload,lambda s,k:({} if s in state else None) if not k else state.get(s,{}).get(k),
        event_type=EVENT,key=key,object_id=digest(value),producer='hybrid-core',
        version=value['accepted_state_version'],registration=('project_fixture','fixture'))


def complete(state,summary=None):
    proofs={k:((EVENT,'hybrid-core',digest(v),v['accepted_state_version']),[(SECTION,k,digest(v))])
            for k,v in state.get(SECTION,{}).items()}
    latest=max(state.get(SECTION,{}).items(),key=lambda item:item[1]['accepted_state_version'],default=None)
    if summary is None:summary=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(proofs))
    validate_complete(state,('project_fixture','fixture'),proofs.get,event_summary=summary)


def test_actual_sources_produce_only_blocked_pure_observation(admission):
    prep,_,_,_,value,state=admission;before=prep.store.audit();key=fact_key(value['request'])
    validate_record(key,value);transition(value,state)
    complete({**state,'version':6,SECTION:{key:value}})
    assert value['status']=='BLOCKED' and all(value[k] is False for k in
        ('release_enabled','execution_enabled','candidate_write_enabled'))
    assert value['gates']['writer_lease']==value['gates']['budget_reservation']=='UNVERIFIED'
    assert prep.store.audit()==before and not prep.store.objects(SECTION)


@pytest.mark.parametrize('damage',['hash','version','boolean','scope','epoch','source_config','expired_source',
    'intent_hash','result_hash','controller_hash','controller_epoch','controller_version','mono_expired',
    'witness_mono_expired','witness_mono_lifetime','witness_boot','witness_hash','witness_snapshot','witness_expired',
    'gate','status','release','write','execution','extra'])
def test_forged_admission_or_permission_upgrade_refused(admission,damage):
    _,_,_,_,original,state=admission;value=deepcopy(original)
    if damage=='hash':value['request_hash']=digest('other')
    elif damage=='version':value['accepted_state_version']=7
    elif damage=='boolean':value['controller_checked_monotonic_ns']=True
    elif damage=='scope':value['request']['project_id']='other';value['request_hash']=digest(value['request'])
    elif damage=='epoch':value['sources']['store_epoch']='other'
    elif damage=='source_config':value['sources']['config_hash']=digest('other')
    elif damage=='expired_source':value['sources']['expires_at']=value['recorded_at']
    elif damage in ('intent_hash','result_hash'):value['preparation'][damage]=digest('other')
    elif damage=='controller_hash':value['controller']['fact_hash']=digest('other')
    elif damage=='controller_epoch':value['controller']['controller_epoch']=2
    elif damage=='controller_version':value['controller']['head_revision']=2
    elif damage=='mono_expired':value['controller_checked_monotonic_ns']+=60*10**9
    elif damage=='witness_mono_expired':value['controller_checked_monotonic_ns']+=30*10**9
    elif damage=='witness_mono_lifetime':value['material_observation_monotonic']['expires_ns']+=1
    elif damage=='witness_boot':value['material_observation_monotonic']['boot_id']='other'
    elif damage=='witness_hash':value['material_observation']['result_hash']=digest('other')
    elif damage=='witness_snapshot':value['material_observation']['snapshot_hash']=digest('other')
    elif damage=='witness_expired':value['material_observation']['expires_at']=value['recorded_at']
    elif damage=='gate':value['gates']['model_access']='VERIFIED'
    elif damage=='status':value['status']='READY'
    elif damage=='release':value['release_enabled']=True
    elif damage=='write':value['candidate_write_enabled']=True
    elif damage=='execution':value['execution_enabled']=True
    else:value['task']={'state':'RUNNING'}
    with pytest.raises(ValueError):transition(value,state)


@pytest.mark.parametrize('damage',['delete','extra','duplicate','details','floating','missing_marker'])
def test_admission_closed_single_fact_event_required(admission,damage):
    _,_,_,_,value,state=admission
    def corrupt(payload):
        if damage=='delete':payload['delete']=[['sessions','anything']]
        elif damage=='extra':payload['put'].append(['tasks','ready',{}])
        elif damage=='duplicate':payload['put'].append(deepcopy(payload['put'][0]))
        elif damage=='details':payload['details']={'grant':True}
        elif damage=='floating':payload['format']=2.0
        else:payload['put']=[r for r in payload['put'] if r[1]]
    with pytest.raises(Conflict):transition(value,state,corrupt)


def test_historical_complete_does_not_require_todays_head_or_token(admission):
    _,_,_,_,value,state=admission;key=fact_key(value['request'])
    from rlflow.hybrid_goals import SECTIONS as goals
    from rlflow.hybrid_authority import SECTIONS as authority
    state={**state,'version':6,SECTION:{key:value},goals[1]:{},authority[2]:{}}
    complete(state)
    with pytest.raises(Conflict):transition(value,{s:v for s,v in state.items() if s!=SECTION})


@pytest.mark.parametrize('damage',['whole_domain','nonlatest_fact'])
def test_historical_summary_protects_even_omitted_nonlatest_fact(admission,damage):
    _,_,_,_,value,state=admission;key=fact_key(value['request']);other=deepcopy(value)
    other['request'].update(idempotency_key='next',expected_state_version=6)
    other['request_hash']=digest(other['request']);other['sources']['source_version']=6;other['accepted_state_version']=7
    otherkey=fact_key(other['request']);summary=((otherkey,7),2)
    state={**state,'version':7,SECTION:{key:value,otherkey:other}};complete(state)
    if damage=='whole_domain':state.pop(SECTION)
    else:del state[SECTION][key]
    with pytest.raises(Conflict):complete(state,summary)


def test_new_admission_cannot_use_old_controller_revision_after_renewal(admission):
    prep,controller,_,_,value,_=admission
    token=controller._tokens[value['controller']['fact_key']]
    controller.renew(token,'new-head',expected_version=5)
    state=prep.store.replay();value=deepcopy(value)
    value['request']['expected_state_version']=6;value['request_hash']=digest(value['request'])
    value['sources']['source_version']=6;value['accepted_state_version']=7
    with pytest.raises(Conflict,match='current head'):transition(value,state)
