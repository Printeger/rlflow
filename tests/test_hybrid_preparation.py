"""Pure preparation fact validation against real fixture source/bundle bytes."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_authority import SECTIONS as AUTHORITY, timestamp
from rlflow.hybrid_goals import SECTIONS as GOALS, digest, head_key
from rlflow.hybrid_preparation import (SECTIONS, EVENTS, intent_key, result_key, source_binding,
    validate_record, validate_transition, validate_complete)
from rlflow.hybrid_snapshot import SnapshotBuilder
from rlflow.hybrid_preparation_sources import load_sources
from rlflow.store import Conflict
from rlflow.store import canonical
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_control_api import setup, login, post, prepare, submit_payload, approve_payload, ORIGIN


@pytest.fixture
def prepared(tmp_path, native_setup):
    adapter, _, candidate, writable, _, calls = native_setup
    config = json.loads(adapter.registry._raw)
    store, _, p, app, pair, _, _ = setup(tmp_path, config=config)
    p['scope']['writable_paths'] = ['module/']
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client); assert post(client, submit_payload(p), headers, 'draft').status_code == 202
        view = prepare(client, p, headers)
        approved = post(client, approve_payload(view), headers, 'approve')
        assert approved.status_code == 202
        fact = store.get(AUTHORITY[0], approved.json()['result']['fact_key'])
    now = timestamp(fact['approved_at'])
    with store.read_connection() as db:
        db.execute('BEGIN')
        loaded = load_sources(store, db, adapter.registry, project_id=pair.drafts.project_id,
            data_mode=pair.drafts.data_mode, store_epoch=pair.drafts.store_epoch,
            goal_ref=head_key(p['project_id'], p['data_mode'], p['goal_id']), now=now)
    (writable/'source.py').write_text('print(42)\n')
    snapshots = tmp_path/'snapshot-control'; snapshots.mkdir(mode=0o700)
    builder = SnapshotBuilder(candidate, ['module/source.py'], snapshots); snapshot = builder.build()
    descriptor = json.loads(snapshot.raw); sources = source_binding(loaded)
    request = {'idempotency_key': 'original-request', 'project_id':p['project_id'], 'data_mode':p['data_mode'],
               'goal_ref':sources['goal_ref'], 'role':'Engineer', 'context':{'text':p['objective']}}
    packet = {'schema_version':'1.0','project_id':p['project_id'],'data_mode':p['data_mode'],
        'store_epoch':sources['store_epoch'],'goal_id':p['goal_id'],'contract_revision':p['contract_version'],
        'proposal_hash':sources['proposal_hash'],'approval_key':sources['approval_key'],
        'candidate_snapshot_hash':descriptor['tree_hash'],'role':request['role'],'context':request['context']}
    plan = adapter.plan_preparation(packet, candidate=snapshot.path, write_roots=[snapshot.path/'module'])
    bundle = adapter.build_preparation(plan)
    value = {'request':request,'request_hash':digest(request),'sources':sources,'plan':json.loads(plan.raw),
        'snapshot':descriptor,'snapshot_id':snapshot.id,'bundle':json.loads(bundle.raw),'created_at':sources['evaluated_at'],
        'accepted_state_version':3,'state':'INTENT','execution_enabled':False}
    key = intent_key(request); state = store.replay()
    return store, adapter, bundle, value, key, state


def transition(section, key, value, state, version):
    payload = {'format':2,'put':[[section,key,value]],'delete':[],'details':None}
    if section not in state: payload['put'].append([section,'',{}])
    validate_transition(payload, lambda s,k:({} if s in state else None) if not k else state.get(s,{}).get(k),
        event_type=EVENTS[SECTIONS.index(section)],key=key,object_id=digest(value),producer='hybrid-core',
        version=version,registration=('project_fixture','fixture'))


def complete(state):
    expected = {key:((EVENTS[SECTIONS.index(section)],'hybrid-core',digest(value),value['accepted_state_version']),
                     [(section,key,digest(value))]) for section in SECTIONS for key,value in state.get(section,{}).items()}
    validate_complete(state,('project_fixture','fixture'),expected.get)


def result(value,key,status='PREPARED'):
    sources = deepcopy(value['sources']); sources['source_version'] = 3
    return {'intent_key':key,'intent_hash':digest(value),'status':status,
        'reason':'MATERIAL_VERIFIED' if status=='PREPARED' else 'RECONCILE_UNKNOWN',
        'material':{'preparation_id':'preparation_'+digest(value['plan']).split(':')[1],
                    'plan_hash':value['bundle']['plan_hash'],'manifest_hash':value['bundle']['seal']['manifest_hash'],
                    'execution_enabled':False} if status=='PREPARED' else None,
        'sources':sources if status=='PREPARED' else None,'recorded_at':value['created_at'],
        'expected_state_version':3,'accepted_state_version':4,'execution_enabled':False}


def test_real_sources_actual_unpublished_expectedseal_are_pure_nonexecuting(prepared):
    store, adapter, bundle, value, key, state = prepared
    before = store.audit(); validate_record(SECTIONS[0],key,value)
    transition(SECTIONS[0],key,value,state,3)
    state = {**state,'version':3,SECTIONS[0]:{key:value}}; complete(state)
    assert bundle.path.exists() and not (adapter.root/bundle.plan_id).exists()
    outcome = result(value,key); rk=result_key(key)
    transition(SECTIONS[1],rk,outcome,state,4)
    state.update(version=4); state[SECTIONS[1]]={rk:outcome}; complete(state)
    # Pure validation does not publish, write facts, charge or start anything.
    assert store.audit()==before and not store.objects(SECTIONS[0]) and not store.objects('sessions')
    with pytest.raises(PermissionError): adapter.start(outcome)


@pytest.mark.parametrize('damage',['request_hash','source_pointer','source_revision','source_scope','source_epoch',
    'source_config','source_expired','snapshot_hash','snapshot_mode','snapshot_size','bundle_hash','file_length',
    'plan_scope','plan_candidate','plan_role','plan_delegation','version','boolean','extra','execution'])
def test_intent_forgery_or_binding_drift_rejected(prepared,damage):
    _, _, _, original, key, state = prepared; value=deepcopy(original)
    if damage=='request_hash':value['request_hash']=digest('changed')
    elif damage=='source_pointer':value['sources']['draft_command_key']='missing'
    elif damage=='source_revision':value['sources']['contract_revision']=2
    elif damage=='source_scope':value['sources']['project_id']='other'
    elif damage=='source_epoch':value['sources']['store_epoch']='store_other'
    elif damage=='source_config':value['sources']['config_hash']=digest('other')
    elif damage=='source_expired':value['sources']['evaluated_at']=value['sources']['expires_at']
    elif damage=='snapshot_hash':value['snapshot']['tree_hash']=digest('other')
    elif damage=='snapshot_mode':value['snapshot']['files'][0]['mode']=0o700
    elif damage=='snapshot_size':value['snapshot']['total_bytes']+=1
    elif damage=='bundle_hash':value['bundle']['seal']['manifest_hash']=digest('other')
    elif damage=='file_length':value['bundle']['seal']['file_lengths']['packet.json']=17*1024**2
    elif damage=='plan_scope':value['plan']['packet']['data_mode']='live'
    elif damage=='plan_candidate':value['plan']['packet']['candidate_snapshot_hash']=digest('other')
    elif damage=='plan_role':value['plan']['packet']['role']='Critic'
    elif damage=='plan_delegation':value['plan']['profile']['native_subagents']=True
    elif damage=='version':value['accepted_state_version']=4
    elif damage=='boolean':value['sources']['source_version']=True
    elif damage=='extra':value['fake_lease']={'valid':True}
    else:value['execution_enabled']=True
    with pytest.raises(ValueError):transition(SECTIONS[0],key,value,state,value['accepted_state_version'])


@pytest.mark.parametrize('status',['UNKNOWN','BLOCKED'])
def test_nonprepared_terminal_fact_has_no_material_or_current_source_grant(prepared,status):
    _, _, _, value,key,state=prepared
    state={**state,'version':3,SECTIONS[0]:{key:value}}
    outcome=result(value,key,status);rk=result_key(key)
    transition(SECTIONS[1],rk,outcome,state,4)
    state.update(version=4);state[SECTIONS[1]]={rk:outcome};complete(state)
    assert outcome['sources'] is None and outcome['material'] is None and outcome['execution_enabled'] is False


@pytest.mark.parametrize('damage',['intent_hash','material_hash','source_config','source_revision','recorded_clock',
                                  'wrong_status','grant','duplicate'])
def test_result_cannot_promote_different_or_revoked_context(prepared,damage):
    _, _, _, value,key,state=prepared;state={**state,'version':3,SECTIONS[0]:{key:value}}
    outcome=result(value,key);rk=result_key(key)
    if damage=='intent_hash':outcome['intent_hash']=digest('other')
    elif damage=='material_hash':outcome['material']['manifest_hash']=digest('other')
    elif damage=='source_config':outcome['sources']['config_hash']=digest('other')
    elif damage=='source_revision':outcome['sources']['contract_revision']=2
    elif damage=='recorded_clock':outcome['recorded_at']=(timestamp(value['created_at'])-timedelta(seconds=1)).isoformat().replace('+00:00','Z')
    elif damage=='wrong_status':outcome['status']='UNKNOWN'
    elif damage=='grant':outcome['execution_enabled']=True
    else:state[SECTIONS[1]]={rk:deepcopy(outcome)}
    with pytest.raises(ValueError):transition(SECTIONS[1],rk,outcome,state,4)


def test_historical_prepared_fact_does_not_require_current_head_or_files(prepared):
    _, _, _, value,key,state=prepared;state={**state,'version':4,SECTIONS[0]:{key:value}}
    outcome=result(value,key);state[SECTIONS[1]]={result_key(key):outcome}
    # Original references/source callbacks remain mandatory, while today's head
    # and filesystem cannot redefine immutable historical claims.
    state[GOALS[1]]={};state[AUTHORITY[2]]={}
    complete(state)
    with pytest.raises(Conflict):transition(SECTIONS[1],result_key(key),outcome,
        {s:v for s,v in state.items() if s!=SECTIONS[1]},4)


def reseal(value):
    """Attacker synchronizes all public hashes; original bindings must still win."""
    value['request_hash'] = digest(value['request'])
    value['snapshot']['total_bytes'] = sum(row['bytes'] for row in value['snapshot']['files'])
    value['snapshot']['tree_hash'] = digest(value['snapshot']['files'])
    value['plan']['packet']['candidate_snapshot_hash'] = value['snapshot']['tree_hash']
    bundle = value['bundle']; seal = bundle['seal']
    bundle['plan_hash'] = seal['manifest']['plan_hash'] = digest(value['plan'])
    for filename, content in (('packet.json', value['plan']['packet']),
                              ('result.schema.json', value['plan']['result_schema'])):
        seal['manifest']['files'][filename] = digest(content)
        seal['file_lengths'][filename] = len(canonical(content))
    seal['manifest_hash'] = digest(seal['manifest'])


@pytest.mark.parametrize('damage', ['profile', 'packet_hash', 'schema_hash', 'packet_length',
    'schema_length', 'nul', 'depth', 'name_bytes', 'directory_count', 'ancestor', 'packet_bytes'])
def test_resynchronized_hashes_do_not_bypass_builder_or_original_profile(prepared, damage):
    _, _, _, original, key, state = prepared; value = deepcopy(original)
    if damage == 'profile': value['plan']['profile']['command_seconds'] += 1
    elif damage in ('nul', 'depth', 'name_bytes', 'directory_count', 'ancestor'):
        names = {'nul': ['bad\x00name'], 'depth': ['/'.join(['a']*65)],
                 'name_bytes': [str(i)+'x'*300 for i in range(4096)],
                 'directory_count': [f'a{i}/b/c' for i in range(2048)],
                 'ancestor': ['module', 'module/source.py']}[damage]
        row = value['snapshot']['files'][0]
        value['snapshot']['files'] = [{**row, 'name': name} for name in sorted(names)]
    elif damage == 'packet_bytes':
        value['request']['context']['text'] = '\U0001f600'*70000
        value['plan']['packet']['context'] = deepcopy(value['request']['context'])
    reseal(value)
    if damage in ('packet_hash', 'schema_hash', 'packet_length', 'schema_length'):
        filename = 'packet.json' if damage.startswith('packet') else 'result.schema.json'
        seal = value['bundle']['seal']
        if damage.endswith('hash'): seal['manifest']['files'][filename] = digest('different bytes')
        else: seal['file_lengths'][filename] += 1
        seal['manifest_hash'] = digest(seal['manifest'])
    with pytest.raises(ValueError): transition(SECTIONS[0], key, value, state, 3)
    with pytest.raises(ValueError): complete({**state, 'version': 3, SECTIONS[0]: {key: value}})


@pytest.mark.parametrize('damage', ['extra', 'set', 'put_type', 'delete_type', 'descriptor', 'format'])
def test_transition_requires_exact_original_event_envelope(prepared, damage):
    _, _, _, value, key, state = prepared
    payload = {'format': 2, 'put': [[SECTIONS[0], key, value]], 'delete': [], 'details': None}
    if damage == 'extra': payload['extra'] = None
    elif damage == 'set': payload['set'] = {}
    elif damage == 'put_type': payload['put'] = tuple(payload['put'])
    elif damage == 'delete_type': payload['delete'] = ()
    elif damage == 'descriptor': payload['put'][0] = tuple(payload['put'][0])
    else: payload['format'] = True
    with pytest.raises(Conflict):
        validate_transition(payload, lambda s,k: state.get(s, {}).get(k), event_type=EVENTS[0],
            key=key, object_id=digest(value), producer='hybrid-core', version=3,
            registration=('project_fixture', 'fixture'))
