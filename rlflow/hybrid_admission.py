"""Pure durable BLOCKED admission observations, never ExecutionLease.

Current conditions/as-of material observations are separate from enforceable
execution gates. All release, execution and candidate-write flags stay false.
"""
from datetime import timedelta

from .hybrid_protocol import ID, HASH, TIME, obj, enum, validate_schema
from .hybrid_goals import digest, check_bytes
from .hybrid_preparation import (SECTIONS as PREPARATION, SOURCES, MATERIAL_OBSERVATION,
    result_key, validate_record as preparation_record, _intent_links, _result_links, _references)
from .hybrid_controller import (SECTIONS as CONTROLLER, validate_record as controller_record,
    fact_key as controller_key, head as controller_head, scope_key)
from .hybrid_authority import timestamp
from .store import Conflict, sha

SECTION='hybrid_admission_facts'
EVENT='HYBRID_ADMISSION_BLOCKED'
COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
POSITIVE={**COUNT,'minimum':1}
REQUEST=obj({'idempotency_key':ID,'project_id':ID,'data_mode':enum('live','fixture'),
    'store_epoch':ID,'preparation_intent_key':ID,'expected_state_version':COUNT})
PREPARATION_REF=obj({'intent_key':ID,'intent_hash':HASH,'result_key':ID,'result_hash':HASH})
CONTROLLER_REF=obj({'fact_key':ID,'fact_hash':HASH,'controller_epoch':POSITIVE,'head_revision':POSITIVE})
GATES=obj({'core_controller':{'const':'CURRENT_POINT_VERIFIED'},
    'source_authority':{'const':'CURRENT_CONDITIONS_VERIFIED'},
    'material_observation':{'const':'VERIFIED_AS_OF'},
    **dict.fromkeys(('legacy_exclusion','model_access','actual_data','os_resources','writer_lease',
                    'budget_reservation','stop_recovery'),{'const':'UNVERIFIED'})})
FACT=obj({'schema_version':{'const':'1.0'},'request':REQUEST,'request_hash':HASH,
    'preparation':PREPARATION_REF,'controller':CONTROLLER_REF,'material_observation':MATERIAL_OBSERVATION,
    'material_observation_monotonic':obj({'boot_id':ID,'issued_ns':COUNT,'expires_ns':POSITIVE}),
    'sources':SOURCES,'recorded_at':TIME,'controller_checked_monotonic_ns':COUNT,
    'accepted_state_version':POSITIVE,'status':{'const':'BLOCKED'},
    'reason':{'const':'EXECUTION_GATES_UNVERIFIED'},'gates':GATES,
    'candidate_write_enabled':{'const':False},'release_enabled':{'const':False},'execution_enabled':{'const':False}})


def fact_key(request):
    return 'admission_fact_'+sha([request['project_id'],request['data_mode'],request['store_epoch'],request['idempotency_key']])


def gates():
    return {key:definition['const'] for key,definition in GATES['properties'].items()}


def validate_record(key,value):
    check_bytes(value,128*1024);validate_schema(FACT,value)
    request=value['request'];sources=value['sources'];obs=value['material_observation'];prep=value['preparation']
    clock=value['material_observation_monotonic'];mono=value['controller_checked_monotonic_ns']
    if (key!=fact_key(request) or value['request_hash']!=digest(request) or
            value['accepted_state_version']!=request['expected_state_version']+1 or
            sources['source_version']!=request['expected_state_version'] or
            any(request[n]!=sources[n] for n in ('project_id','data_mode','store_epoch')) or
            request['preparation_intent_key']!=prep['intent_key'] or prep['result_key']!=result_key(prep['intent_key']) or
            any(obs[n]!=prep[n] for n in ('intent_key','intent_hash','result_key','result_hash')) or
            value['recorded_at']!=sources['evaluated_at'] or
            not timestamp(obs['checked_at'])<=timestamp(value['recorded_at'])<timestamp(obs['expires_at']) or
            timestamp(obs['expires_at'])-timestamp(obs['checked_at'])!=timedelta(seconds=30) or
            clock['expires_ns']-clock['issued_ns']!=30*10**9 or not clock['issued_ns']<=mono<clock['expires_ns'] or
            timestamp(sources['evaluated_at'])>=timestamp(sources['expires_at']) or
            not sources['draft_source_version']<=sources['approval_source_version']<=sources['source_version']):
        raise Conflict('admission identity, source or as-of lifetime differs')
    counters=[request['expected_state_version'],value['accepted_state_version'],value['controller_checked_monotonic_ns'],
        value['controller']['controller_epoch'],value['controller']['head_revision'],
        clock['issued_ns'],clock['expires_ns'],
        *(sources[n] for n in ('source_version','contract_revision','authority_revision','draft_source_version','approval_source_version'))]
    if any(type(v) is not int for v in counters):raise Conflict('actual admission integers required')


def validate_persisted(state):
    for key,value in state.get(SECTION,{}).items():validate_record(key,value)


def validate_links(value,lookup,*,current=False):
    """Original dependencies; current heads only for a new transition."""
    request=value['request'];ref=value['preparation'];cr=value['controller'];sources=value['sources']
    intent=lookup(PREPARATION[0],ref['intent_key']);outcome=lookup(PREPARATION[1],ref['result_key'])
    control=lookup(CONTROLLER[0],cr['fact_key'])
    if intent is None or outcome is None or control is None:raise Conflict('admission original references missing')
    preparation_record(PREPARATION[0],ref['intent_key'],intent)
    preparation_record(PREPARATION[1],ref['result_key'],outcome)
    controller_record(CONTROLLER[0],cr['fact_key'],control)
    _intent_links(intent,lookup);_result_links(outcome,intent,lookup)
    _references(sources,lookup,current=current)
    observed=value['material_observation'];old=intent['sources'];owner=control['request']
    if current and lookup(CONTROLLER[1],scope_key(owner['project_id'],owner['data_mode']))!=controller_head(control):
        raise Conflict('admission controller is not the current head')
    if (outcome['status']!='PREPARED' or ref['intent_hash']!=digest(intent) or ref['result_hash']!=digest(outcome) or
            max(intent['accepted_state_version'],outcome['accepted_state_version'],control['accepted_state_version'])>=value['accepted_state_version'] or
            any(sources[n]!=old[n] for n in old if n not in ('evaluated_at','source_version')) or
            cr!={'fact_key':controller_key(owner),'fact_hash':digest(control),
                 'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            any(owner[n]!=request[n] for n in ('project_id','data_mode','store_epoch')) or
            control['config_hash']!=sources['config_hash'] or
            value['material_observation_monotonic']['boot_id']!=owner['owner']['process']['boot_id'] or
            not timestamp(control['issued_at'])<=timestamp(value['recorded_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns'] or
            timestamp(observed['checked_at'])<timestamp(outcome['recorded_at']) or
            observed['snapshot_id']!=intent['snapshot_id'] or observed['snapshot_hash']!=intent['snapshot']['tree_hash'] or
            observed['plan_hash']!=intent['bundle']['plan_hash'] or
            observed['manifest_hash']!=intent['bundle']['seal']['manifest_hash']):
        raise Conflict('admission original preparation/controller binding differs')


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (set(payload)!={'format','put','delete','details'} or type(payload.get('format')) is not int or payload['format']!=2 or
            payload['details'] is not None or type(payload['put']) is not list or type(payload['delete']) is not list or payload['delete']):
        raise Conflict('admission requires closed append transaction')
    rows=[];markers=[];seen=set()
    for item in payload['put']:
        if type(item) is not list or len(item)!=3 or type(item[0]) is not str or type(item[1]) is not str:
            raise Conflict('admission descriptor invalid')
        section,objkey,value=item
        if section!=SECTION or objkey in seen:raise Conflict('admission extra or duplicate mutation')
        seen.add(objkey)
        if not objkey:markers.append(value)
        else:rows.append((objkey,value))
    expected_markers=[{}] if lookup(SECTION,'') is None else []
    if len(rows)!=1 or markers!=expected_markers:raise Conflict('admission single fact/initial marker required')
    objkey,value=rows[0];validate_record(objkey,value)
    if (lookup(SECTION,objkey) is not None or event_type!=EVENT or key!=objkey or object_id!=digest(value) or
            producer!='hybrid-core' or value['accepted_state_version']!=version or
            registration!=(value['request']['project_id'],value['request']['data_mode'])):
        raise Conflict('admission original event binding differs')
    validate_links(value,lookup,current=True)


def validate_complete(state,registration=None,event_lookup=None,*,event_summary=(None,0)):
    validate_persisted(state);facts=state.get(SECTION,{})
    lookup=lambda s,k:state.get(s,{}).get(k)
    for key,value in facts.items():
        if (value['accepted_state_version']>state['version'] or event_lookup is None or event_lookup(key)!=(
                (EVENT,'hybrid-core',digest(value),value['accepted_state_version']),[(SECTION,key,digest(value))]) or
                registration!=(value['request']['project_id'],value['request']['data_mode'])):
            raise Conflict('admission original event proof differs')
        validate_links(value,lookup)
    latest=max(facts.items(),key=lambda item:item[1]['accepted_state_version'],default=None)
    expected=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(facts))
    if event_summary!=expected:raise Conflict('admission historical domain differs from original events')
