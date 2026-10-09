"""Immutable fixed core-applied candidate output, never a reconstructed writer."""
from .hybrid_protocol import ID,HASH,TIME,obj,validate_schema
from .hybrid_goals import digest,check_bytes
from .hybrid_preparation import SOURCES,_references
from .hybrid_admission import CONTROLLER_REF
from .hybrid_controller import SECTIONS as CONTROL,fact_key as control_key,head as control_head,scope_key
from .hybrid_working_plan import TREE,_tree
from .hybrid_budget_ledger import SECTIONS as BUDGET,validate_record as budget_record,validate_links as budget_links
from .hybrid_engineering_patch import KIND,TARGET,BEFORE,AFTER,hash_bytes,validate_result
from .hybrid_authority import timestamp
from .store import Conflict,sha,canonical

SECTIONS=('hybrid_candidate_output_intents','hybrid_candidate_output_results')
EVENTS=('HYBRID_CANDIDATE_OUTPUT_INTENT','HYBRID_CANDIDATE_OUTPUT_RECORDED')
COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
REFERENCE=obj({'key':ID,'hash':HASH})
SCOPE=obj({'project_id':ID,'data_mode':{'const':'fixture'},'store_epoch':ID,'goal_ref':ID,
    'idempotency_key':ID,'expected_state_version':COUNT,'terminal_key':ID,'terminal_hash':HASH})
SCOPE['properties']['intent_key']=ID
SCOPE['properties']['intent_hash']=HASH
COMMON={'schema_version':{'const':'1.0'},'request':SCOPE,'request_hash':HASH,
    'accepted_state_version':{**COUNT,'minimum':1},'recorded_at':TIME,'sources':SOURCES,
    'controller':CONTROLLER_REF,'controller_checked_monotonic_ns':COUNT,
    'pool_free':{'type':'object'},'result_hash':HASH,
    'base_tree':TREE,'target':{'const':TARGET},
    'target_identity':{'type':'array','minItems':2,'maxItems':2,'items':COUNT},
    'before_sha256':{'const':hash_bytes(BEFORE)},'after_sha256':{'const':hash_bytes(AFTER)},
    'goal_completed':{'const':False},'independent_review_status':{'const':'NOT_PERFORMED'},
    'dispatch_enabled':{'const':False}}
INTENT=obj({**COMMON,'state':{'const':'FIXED_WRITE_INTENT'},'execution_authority':{'const':'ACTUAL_ORIGINAL_CORE_APPLIER_ONLY'}})
RESULT=obj({**COMMON,'state':{'const':'OUTPUT_CAPTURED_AUDIT_ONLY'},'output_tree':TREE,
    'actual_tests':{'type':'array','minItems':3,'maxItems':3,'items':obj({
        'left':{'type':'integer'},'right':{'type':'integer'},'expected':{'type':'integer'},'actual':{'type':'integer'}})},
    'candidate_write_performed':{'const':True},'candidate_write_fd_closed':{'const':True}})


def intent_key(request):
    return 'candidate_output_'+sha([request['project_id'],request['data_mode'],request['store_epoch'],request['idempotency_key']])


def result_key(request):return 'candidate_output_result_'+sha(request['intent_key'])


def validate_record(section,key,value):
    if section not in SECTIONS:raise Conflict('unknown candidate output section')
    check_bytes(value,4*1024**2);validate_schema(INTENT if section==SECTIONS[0] else RESULT,value)
    request=value['request'];_tree(value['base_tree'])
    counters=[request['expected_state_version'],value['accepted_state_version'],value['controller_checked_monotonic_ns'],
        value['controller']['controller_epoch'],value['controller']['head_revision']]
    counters.extend(value['sources'][k] for k in ('source_version','contract_revision','authority_revision',
        'draft_source_version','approval_source_version'))
    if any(type(v) is not int for v in counters):raise Conflict('candidate output actual integer required')
    if (key!=(intent_key(request) if section==SECTIONS[0] else result_key(request)) or
            value['request_hash']!=digest(request) or value['accepted_state_version']!=request['expected_state_version']+1 or
            value['sources']['source_version']!=request['expected_state_version'] or
            any(value['sources'][k]!=request[k] for k in ('project_id','data_mode','store_epoch','goal_ref')) or
            timestamp(value['recorded_at'])<timestamp(value['sources']['evaluated_at']) or
            not timestamp(value['sources']['evaluated_at'])<timestamp(value['sources']['expires_at']) or
            type(value['controller_checked_monotonic_ns']) is not int or
            any(type(v) is not int for v in value['target_identity']) or
            any(type(value[k]) is not bool for k in ('goal_completed','dispatch_enabled'))):
        raise Conflict('candidate output immutable identity/source differs')
    if section==SECTIONS[0] and value['recorded_at']!=value['sources']['evaluated_at']:
        raise Conflict('candidate write intent requires current authorization sample')
    pair='intent_key' in request and 'intent_hash' in request
    if ('intent_key' in request)!=('intent_hash' in request) or pair!=(section==SECTIONS[1]):
        raise Conflict('candidate output original intent pair differs')
    if section==SECTIONS[1]:
        _tree(value['output_tree'])
        expected=[{'left':a,'right':b,'expected':a+b,'actual':a+b} for a,b in ((2,3),(-4,2),(0,0))]
        if (canonical(value['actual_tests'])!=canonical(expected) or value['candidate_write_performed'] is not True or
                value['candidate_write_fd_closed'] is not True):raise Conflict('candidate output actual fixed tests required')


def validate_links(section,value,lookup,*,current=False):
    request=value['request'];terminal=lookup(BUDGET[0],request['terminal_key'])
    if terminal is None:raise Conflict('candidate output original terminal missing')
    budget_record(BUDGET[0],request['terminal_key'],terminal);budget_links(terminal,lookup)
    runtime=terminal['request'].get('fixture_runtime',{});origin=runtime.get('origin',{})
    result=runtime.get('engineering_patch_result')
    if (terminal['decision']!='SETTLED' or runtime.get('phase')!='FIXTURE_SCOPE_STOPPED' or origin.get('kind')!=KIND or
            result is None or digest(terminal)!=request['terminal_hash'] or digest(result)!=value['result_hash'] or
            terminal['accepted_state_version']>=value['accepted_state_version'] or
            timestamp(terminal['recorded_at'])>timestamp(value['recorded_at']) or
            any(terminal['request'][k]!=request[k] for k in ('project_id','data_mode','store_epoch','goal_ref')) or
            any(value['sources'][k]!=v for k,v in terminal['policy_source'].items() if k not in ('source_version','evaluated_at'))):
        raise Conflict('candidate output original engineering terminal/source differs')
    validate_result(result,origin,runtime['producer'])
    # RESULT carries the original valid write authorization, not renewed
    # authority at receipt time. Its later timestamp is audit-only.
    _references(value['sources'],lookup,current=current and section==SECTIONS[0])
    cr=value['controller'];control=lookup(CONTROL[0],cr['fact_key'])
    if (control is None or control['accepted_state_version']>=value['accepted_state_version'] or
            cr!={'fact_key':control_key(control['request']),'fact_hash':digest(control),
                'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            any(control['request'][k]!=request[k] for k in ('project_id','data_mode','store_epoch')) or
            control['config_hash']!=value['sources']['config_hash'] or
            not timestamp(control['issued_at'])<=timestamp(value['sources']['evaluated_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns']):
        raise Conflict('candidate output original controller/authorization sample differs')
    if current and section==SECTIONS[0] and lookup(CONTROL[1],scope_key(request['project_id'],request['data_mode']))!=control_head(control):
        raise Conflict('candidate output controller no longer current')
    from .hybrid_host_pool_ledger import validate as pool_validate
    free=pool_validate(value['pool_free']);payload=free['payload']
    closed={'lease_id':origin['lease_id'],'claim_sha256':origin['pool_claim']['hash'],
        'terminal_sha256':runtime['terminal_proof_sha256'],'all_original_pool_fds_closed':True}
    if (free['action']!='FIXTURE_FREE' or free['pool_id']!=origin['pool_id'] or
            free['key']!='fixture_free_'+sha([origin['pool_claim']['key'],origin['lease_id']]) or
            payload['claim_key']!=origin['pool_claim']['key'] or payload['claim_hash']!=origin['pool_claim']['hash'] or
            payload['runtime_lease_id']!=origin['lease_id'] or payload['project_fact_key']!=request['terminal_key'] or
            payload['project_fact_hash']!=request['terminal_hash'] or
            payload['close_witness_hash']!=digest(closed)):raise Conflict('candidate output original Pool FREE differs')
    from .hybrid_working_plan import SECTIONS as PLANS
    plan=lookup(PLANS[0],origin['working_plan_intent']['key'])
    if plan is None or value['base_tree']!=plan['plan']['working_tree']:
        raise Conflict('candidate output original base tree differs')
    base={row['name']:row for row in value['base_tree']['files']}
    if TARGET not in base or base[TARGET]['sha256']!=hash_bytes(BEFORE) or base[TARGET]['bytes']!=len(BEFORE):
        raise Conflict('candidate output exact original base file required')
    if section==SECTIONS[1]:
        prior=lookup(SECTIONS[0],request['intent_key'])
        if prior is None:raise Conflict('candidate output original intent missing')
        validate_record(SECTIONS[0],request['intent_key'],prior)
        validate_links(SECTIONS[0],prior,lookup)
        if (digest(prior)!=request['intent_hash'] or prior['accepted_state_version']>=value['accepted_state_version'] or
                timestamp(prior['recorded_at'])>timestamp(value['recorded_at']) or
                any(prior[k]!=value[k] for k in ('base_tree','target','target_identity','before_sha256','after_sha256','result_hash','pool_free',
                    'controller','controller_checked_monotonic_ns')) or
                any(prior['sources'][k]!=v for k,v in value['sources'].items() if k!='source_version') or
                any(prior['request'][k]!=request[k] for k in ('project_id','data_mode','store_epoch','goal_ref','terminal_key','terminal_hash'))):
            raise Conflict('candidate output original intent linkage differs')
        expected={**value['base_tree'],'files':[{**row,'bytes':len(AFTER),'sha256':hash_bytes(AFTER)} if row['name']==TARGET else row for row in value['base_tree']['files']]}
        expected['total_bytes']=value['base_tree']['total_bytes']-len(BEFORE)+len(AFTER)
        expected['tree_hash']=digest({k:v for k,v in expected.items() if k not in ('tree_hash','execution_enabled')})
        if canonical(expected)!=canonical(value['output_tree']):raise Conflict('candidate output changed non-target inventory')


def event_inputs(value):
    request=value['request'];result={'terminal_key':request['terminal_key'],'terminal_hash':request['terminal_hash'],
        'result_hash':value['result_hash'],'base_tree_hash':value['base_tree']['tree_hash'],'proposal_hash':value['sources']['proposal_hash']}
    if 'intent_key' in request:result.update(intent_key=request['intent_key'],intent_hash=request['intent_hash'])
    return result


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or type(payload['format']) is not int or
            payload['format']!=2 or type(payload['delete']) is not list or payload['delete']!=[] or
            payload['details'] is not None or type(payload['put']) is not list):
        raise Conflict('closed candidate output transaction required')
    section=SECTIONS[EVENTS.index(event_type)] if event_type in EVENTS else None
    rows=[];markers=[];seen=set()
    for row in payload['put']:
        if type(row) is not list or len(row)!=3 or row[0]!=section or type(row[1]) is not str or row[1] in seen:
            raise Conflict('candidate output mutation differs')
        seen.add(row[1]);(rows if row[1] else markers).append(row if row[1] else row[2])
    if len(rows)!=1 or markers!=([{}] if lookup(section,'') is None else []):raise Conflict('candidate output single fact/marker required')
    _,actual,value=rows[0];validate_record(section,actual,value)
    if (actual!=key or lookup(section,key) is not None or object_id!=digest(value) or producer!='hybrid-core' or
            version!=value['accepted_state_version'] or registration!=(value['request']['project_id'],'fixture')):
        raise Conflict('candidate output original event identity differs')
    validate_links(section,value,lookup,current=True)


def validate_persisted(state):
    for section in SECTIONS:
        for key,value in state.get(section,{}).items():validate_record(section,key,value)


def validate_complete(state,registration,event_lookup,summary):
    validate_persisted(state);lookup=lambda s,k:state.get(s,{}).get(k)
    for section,event in zip(SECTIONS,EVENTS):
        facts=state.get(section,{})
        for key,value in facts.items():
            if (value['accepted_state_version']>state['version'] or registration!=(value['request']['project_id'],'fixture') or
                    event_lookup(key)!=((event,'hybrid-core',digest(value),value['accepted_state_version']),[(section,key,digest(value))])):
                raise Conflict('candidate output original historical event differs')
            validate_links(section,value,lookup)
        latest=max(facts.items(),key=lambda item:item[1]['accepted_state_version'],default=None)
        if summary(section,state['version'])!=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(facts)):
            raise Conflict('candidate output historical domain differs')
