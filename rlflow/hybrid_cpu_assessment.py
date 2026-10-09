"""Immutable finite-trial appraisal, not Goal completion or dispatch authority."""
from .hybrid_protocol import ID, HASH, TIME, obj, enum, validate_schema
from .hybrid_goals import digest, check_bytes
from .hybrid_preparation import SOURCES, _references
from .hybrid_admission import CONTROLLER_REF
from .hybrid_controller import SECTIONS as CONTROL, fact_key as control_key, head as control_head, scope_key
from .hybrid_budget_ledger import SECTIONS as BUDGET, validate_record as budget_record, validate_links as budget_links
from .hybrid_cpu_trial import KIND, PROFILE, validate_result
from .hybrid_authority import timestamp
from .store import Conflict, sha

SECTION = 'hybrid_cpu_trial_assessments'
EVENT = 'HYBRID_CPU_TRIAL_ASSESSED'
COUNT = {'type':'integer','minimum':0,'maximum':2**63-1}
REQUEST = obj({'project_id':ID,'data_mode':{'const':'fixture'},'store_epoch':ID,
    'idempotency_key':ID,'expected_state_version':COUNT,'goal_ref':ID,'terminal_key':ID})
ASSESSMENT = obj({'profile':{'const':PROFILE},
    'execution_status':enum('SUCCEEDED','NOT_EXECUTED','RESULT_UNAVAILABLE'),
    'scientific_validity':enum('VALID','UNASSESSED'),
    'hypothesis_outcome':enum('SUPPORTED','REFUTED','INCONCLUSIVE'),
    'interpretation_scope':{'const':'PINNED_THREE_SEEDS_ONLY'},
    'next_action':enum('REQUEST_INDEPENDENT_REVIEW','NO_AUTOMATIC_RETRY'),
    'condition_coverage':{'type':'array','maxItems':0},
    'independent_review_status':{'const':'NOT_PERFORMED'},
    'goal_completed':{'const':False},'dispatch_enabled':{'const':False}})
FACT = obj({'schema_version':{'const':'1.0'},'request':REQUEST,'request_hash':HASH,
    'terminal_hash':HASH,'result_hash':{'oneOf':[HASH,{'type':'null'}]},'pool_free':{'type':'object'},
    'sources':SOURCES,'controller':CONTROLLER_REF,'recorded_at':TIME,
    'controller_checked_monotonic_ns':COUNT,'accepted_state_version':{**COUNT,'minimum':1},
    'assessment':ASSESSMENT,'evidence_activation':{'const':'EXPERIMENT_CURRENT_AS_OF'}})


def fact_key(request):
    return 'cpu_assessment_'+sha([request['project_id'],request['data_mode'],request['store_epoch'],request['idempotency_key']])


def appraisal(terminal):
    runtime = terminal['request'].get('fixture_runtime',{})
    if (terminal['decision']!='SETTLED' or runtime.get('phase')!='FIXTURE_SCOPE_STOPPED' or
            runtime.get('origin',{}).get('kind')!=KIND):
        raise Conflict('original terminal CPU trial required for appraisal')
    value = runtime.get('cpu_trial_result')
    if value is not None: validate_result(value,runtime['origin'],runtime['producer'])
    return {'profile':PROFILE,
        'execution_status':'SUCCEEDED' if value is not None else
            'RESULT_UNAVAILABLE' if runtime['cpu_trial_release_attempted'] else 'NOT_EXECUTED',
        'scientific_validity':'VALID' if value is not None else 'UNASSESSED',
        'hypothesis_outcome':('SUPPORTED' if value['hypothesis_supported'] else 'REFUTED') if value is not None else 'INCONCLUSIVE',
        'interpretation_scope':'PINNED_THREE_SEEDS_ONLY',
        'next_action':'REQUEST_INDEPENDENT_REVIEW' if value is not None else 'NO_AUTOMATIC_RETRY',
        'condition_coverage':[],'independent_review_status':'NOT_PERFORMED',
        'goal_completed':False,'dispatch_enabled':False}


def validate_record(key,value):
    check_bytes(value,128*1024); validate_schema(FACT,value)
    request=value['request']; sources=value['sources']
    if (key!=fact_key(request) or value['request_hash']!=digest(request) or
            type(request['expected_state_version']) is not int or
            value['accepted_state_version']!=request['expected_state_version']+1 or
            sources['source_version']!=request['expected_state_version'] or
            any(request[n]!=sources[n] for n in ('project_id','data_mode','store_epoch','goal_ref')) or
            value['recorded_at']!=sources['evaluated_at'] or
            not timestamp(value['recorded_at'])<timestamp(sources['expires_at'])):
        raise Conflict('CPU appraisal immutable request/source identity differs')


def validate_links(value,lookup,*,current=False):
    request=value['request']; terminal=lookup(BUDGET[0],request['terminal_key'])
    if terminal is None: raise Conflict('CPU appraisal original terminal missing')
    budget_record(BUDGET[0],request['terminal_key'],terminal); budget_links(terminal,lookup)
    runtime=terminal['request']['fixture_runtime']; result=runtime.get('cpu_trial_result')
    from .hybrid_host_pool_ledger import validate as pool_validate
    free=pool_validate(value['pool_free']); origin=runtime['origin']; fp=free['payload']
    if (free['action']!='FIXTURE_FREE' or free['pool_id']!=origin['pool_id'] or
            free['key']!='fixture_free_'+sha([origin['pool_claim']['key'],origin['lease_id']]) or
            fp['claim_key']!=origin['pool_claim']['key'] or fp['claim_hash']!=origin['pool_claim']['hash'] or
            fp['runtime_lease_id']!=origin['lease_id'] or fp['project_fact_key']!=request['terminal_key'] or
            fp['project_fact_hash']!=value['terminal_hash']):
        raise Conflict('CPU appraisal original Pool FREE binding differs')
    if (value['terminal_hash']!=digest(terminal) or value['result_hash']!=(None if result is None else digest(result)) or
            value['assessment']!=appraisal(terminal) or terminal['accepted_state_version']>=value['accepted_state_version'] or
            timestamp(value['recorded_at'])<timestamp(terminal['recorded_at']) or
            any(request[n]!=terminal['request'][n] for n in ('project_id','data_mode','store_epoch','goal_ref')) or
            any(value['sources'][n]!=v for n,v in terminal['policy_source'].items()
                if n not in ('source_version','evaluated_at'))):
        raise Conflict('CPU appraisal differs from original trial/approved revision')
    _references(value['sources'],lookup,current=current)
    cr=value['controller']; control=lookup(CONTROL[0],cr['fact_key'])
    if (control is None or control['accepted_state_version']>=value['accepted_state_version'] or
            cr!={'fact_key':control_key(control['request']),'fact_hash':digest(control),
            'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            any(control['request'][n]!=request[n] for n in ('project_id','data_mode','store_epoch')) or
            control['config_hash']!=value['sources']['config_hash'] or
            not timestamp(control['issued_at'])<=timestamp(value['recorded_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns']):
        raise Conflict('CPU appraisal original controller differs')
    if current and lookup(CONTROL[1],scope_key(request['project_id'],request['data_mode']))!=control_head(control):
        raise Conflict('CPU appraisal controller no longer current')


def event_inputs(value):
    return {'terminal_key':value['request']['terminal_key'],'terminal_hash':value['terminal_hash'],
        'proposal_hash':value['sources']['proposal_hash'],'result_hash':value['result_hash']}


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
            type(payload['format']) is not int or payload['format']!=2 or payload['delete']!=[] or
            payload['details'] is not None or type(payload['put']) is not list):
        raise Conflict('closed CPU appraisal append transaction required')
    rows=[];markers=[];seen=set()
    for item in payload['put']:
        if type(item) is not list or len(item)!=3 or item[0]!=SECTION or type(item[1]) is not str or item[1] in seen:
            raise Conflict('CPU appraisal extra/duplicate/invalid mutation')
        seen.add(item[1]); (rows if item[1] else markers).append(item if item[1] else item[2])
    if len(rows)!=1 or markers!=([{}] if lookup(SECTION,'') is None else []):
        raise Conflict('CPU appraisal single fact/initial marker required')
    _,objkey,value=rows[0]; validate_record(objkey,value)
    if (lookup(SECTION,objkey) is not None or event_type!=EVENT or key!=objkey or object_id!=digest(value) or
            producer!='hybrid-core' or version!=value['accepted_state_version'] or
            registration!=(value['request']['project_id'],value['request']['data_mode'])):
        raise Conflict('CPU appraisal original event binding differs')
    validate_links(value,lookup,current=True)


def validate_persisted(state):
    for key,value in state.get(SECTION,{}).items(): validate_record(key,value)


def validate_complete(state,registration,event_lookup,event_summary):
    validate_persisted(state); facts=state.get(SECTION,{})
    lookup=lambda s,k:state.get(s,{}).get(k)
    for key,value in facts.items():
        if (value['accepted_state_version']>state['version'] or
                registration!=(value['request']['project_id'],value['request']['data_mode']) or
                event_lookup(key)!=((EVENT,'hybrid-core',digest(value),value['accepted_state_version']),[(SECTION,key,digest(value))])):
            raise Conflict('CPU appraisal original historical event differs')
        validate_links(value,lookup)
    latest=max(facts.items(),key=lambda item:item[1]['accepted_state_version'],default=None)
    expected=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(facts))
    if event_summary!=expected: raise Conflict('CPU appraisal historical domain differs from events')
