"""Append-only original A condition acceptance. Pure validators never issue authority."""
from .hybrid_protocol import ID,HASH,TIME,obj,array,enum,validate_schema
from .hybrid_goals import digest,check_bytes
from .hybrid_preparation import SOURCES,_references
from .hybrid_admission import CONTROLLER_REF
from .hybrid_controller import SECTIONS as CONTROL,head as control_head,scope_key,fact_key as control_key
from .hybrid_budget_ledger import SECTIONS as BUDGET,derived_heads,scope,validate_record as budget_record,validate_links as budget_links
from .hybrid_budget import account_key,validate_balances
from .hybrid_authority import SECTIONS as AUTHORITY,timestamp
from .hybrid_goals import SECTIONS as GOALS
from .hybrid_a_condition_rules import derive
from .store import Conflict,sha,canonical

SECTION='hybrid_a_condition_acceptances'
EVENT='HYBRID_A_CONDITIONS_ACCEPTED'
COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
REF=obj({'key':ID,'hash':HASH})
PARENTS=obj({k:REF for k in ('engineer','cpu','reviewer')})
EVIDENCE=obj({'condition_id':ID,'condition_sha256':HASH,'candidate_sha256':HASH,
    'configuration_sha256':HASH,'evaluation_data_sha256':HASH,'evaluation_rule_sha256':HASH,
    'verifier':enum('ORIGINAL_CPU_CHECKS_V1','ORIGINAL_INDEPENDENT_REVIEW_V1'),
    'verdict':{'const':'PASS'},'implementer_session_id':{'type':'string','minLength':1,'maxLength':160},
    'reviewer_session_id':{'type':'string','minLength':1,'maxLength':160},'original_event_refs':PARENTS})
REQUEST=obj({'project_id':ID,'data_mode':enum('live','fixture'),'store_epoch':ID,'goal_ref':ID,
    'idempotency_key':ID,'expected_state_version':COUNT,'reviewer_terminal_key':ID})
FACT=obj({'schema_version':{'const':'1.0'},'request':REQUEST,'request_hash':HASH,
    'sources':SOURCES,'controller':CONTROLLER_REF,'recorded_at':TIME,
    'controller_checked_monotonic_ns':COUNT,'accepted_state_version':{**COUNT,'minimum':1},
    'parents':PARENTS,'candidate_sha256':HASH,'evidence':{**array(EVIDENCE,200),'minItems':2},
    'required_conditions_passed':{'type':'integer','minimum':2,'maximum':200},
    'budget_head_sha256':HASH,'goal_completed':{'const':False},'dispatch_enabled':{'const':False}})


def fact_key(request):
    return 'a_conditions_'+sha([request[k] for k in
        ('project_id','data_mode','store_epoch','goal_ref','reviewer_terminal_key')])


def event_inputs(value):
    return {'reviewer_terminal_key':value['request']['reviewer_terminal_key'],
        'parents':value['parents'],'proposal_hash':value['sources']['proposal_hash'],
        'candidate_sha256':value['candidate_sha256']}


def validate_record(key,value):
    check_bytes(value,256*1024);validate_schema(FACT,value)
    request=value['request'];sources=value['sources']
    if (key!=fact_key(request) or value['request_hash']!=digest(request) or
            type(request['expected_state_version']) is not int or
            value['accepted_state_version']!=request['expected_state_version']+1 or
            sources['source_version']!=request['expected_state_version'] or
            any(request[k]!=sources[k] for k in ('project_id','data_mode','store_epoch','goal_ref')) or
            value['recorded_at']!=sources['evaluated_at'] or
            not timestamp(value['recorded_at'])<timestamp(sources['expires_at']) or
            value['parents']['reviewer']['key']!=request['reviewer_terminal_key'] or
            type(value['goal_completed']) is not bool or type(value['dispatch_enabled']) is not bool):
        raise Conflict('condition acceptance immutable request/source identity differs')


def validate_links(value,lookup,*,current=False):
    parents={}
    for name,ref in value['parents'].items():
        parent=lookup(BUDGET[0],ref['key'])
        if parent is None or digest(parent)!=ref['hash']:raise Conflict('condition original parent missing or changed')
        budget_record(BUDGET[0],ref['key'],parent);budget_links(parent,lookup);parents[name]=parent
    sources=value['sources'];request=value['request']
    record=lookup(GOALS[0],sources['contract_key']);approval=lookup(AUTHORITY[0],sources['approval_key'])
    if record is None or approval is None:raise Conflict('condition original contract/approval missing')
    result=derive(record['contract']['proposal'],approval['registry_witness'],
        parents['cpu'],parents['engineer'],parents['reviewer'])
    if any(value[k]!=v for k,v in result.items()):raise Conflict('condition evidence differs from original candidate chain')
    reviewer=parents['reviewer']
    head=derived_heads(reviewer)[BUDGET[1]][account_key(scope(reviewer['request']))]
    from .hybrid_a_workflow_accounting import check_window
    check_window(head['workflow'],reviewer['request']['fixture_runtime']['origin']['native_model']['workflow'],
        timestamp(value['recorded_at']))
    base=validate_balances(head['balance'])
    if (value['budget_head_sha256']!=digest(head) or any(base['reserved'].values()) or
            any(base['unknown_exposure'].values()) or any(r['overrun'] for r in head['balance'].values()) or
            reviewer['accepted_state_version']>=value['accepted_state_version'] or
            timestamp(reviewer['recorded_at'])>timestamp(value['recorded_at']) or
            any(request[k]!=reviewer['request'][k] for k in ('project_id','data_mode','store_epoch','goal_ref')) or
            any(sources[k]!=reviewer['policy_source'][k] for k in
                ('proposal_hash','approval_hash','config_hash','scope_hash'))):
        raise Conflict('condition original complete budget/scope/approval required')
    if current and lookup(BUDGET[1],account_key(scope(request)))!=head:
        raise Conflict('condition original current Goal budget head changed')
    _references(sources,lookup,current=current)
    cr=value['controller'];control=lookup(CONTROL[0],cr['fact_key'])
    if (control is None or cr!={'fact_key':control_key(control['request']),'fact_hash':digest(control),
            'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            control['accepted_state_version']>=value['accepted_state_version'] or
            any(control['request'][k]!=request[k] for k in ('project_id','data_mode','store_epoch')) or
            control['config_hash']!=sources['config_hash'] or
            not timestamp(control['issued_at'])<=timestamp(value['recorded_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns']):
        raise Conflict('condition acceptance original Controller differs')
    if current and lookup(CONTROL[1],scope_key(request['project_id'],request['data_mode']))!=control_head(control):
        raise Conflict('condition acceptance Controller no longer current')


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
            type(payload['format']) is not int or payload['format']!=2 or payload['delete']!=[] or
            payload['details'] is not None or type(payload['put']) is not list):
        raise Conflict('closed condition acceptance append transaction required')
    rows=[];markers=[];seen=set()
    for item in payload['put']:
        if (type(item) is not list or len(item)!=3 or item[0]!=SECTION or
                type(item[1]) is not str or item[1] in seen):
            raise Conflict('condition acceptance extra/duplicate mutation')
        seen.add(item[1]);(rows if item[1] else markers).append(item if item[1] else item[2])
    if len(rows)!=1 or markers!=([{}] if lookup(SECTION,'') is None else []):
        raise Conflict('condition acceptance single fact/initial marker required')
    _,objkey,value=rows[0];validate_record(objkey,value)
    if (lookup(SECTION,objkey) is not None or key!=objkey or event_type!=EVENT or
            object_id!=digest(value) or producer!='hybrid-core' or version!=value['accepted_state_version'] or
            registration!=(value['request']['project_id'],value['request']['data_mode'])):
        raise Conflict('condition acceptance original event differs')
    validate_links(value,lookup,current=True)


def original_event(store,db,key,read):
    fields=['seq','previous_state_version','new_state_version','object_version']
    fields += [f"CASE WHEN typeof({name})='text' AND length(CAST({name} AS BLOB))<={limit} THEN {name} END AS {name}"
        for name,limit in (('event_type',64),('producer',64),('object_id',128),
            ('payload_sha256',64),('input_versions',4096))]
    fields.append("CASE WHEN typeof(payload)='text' AND length(CAST(payload AS BLOB))<=? THEN payload END AS payload")
    row=db.execute('SELECT '+','.join(fields)+' FROM events WHERE idempotency_key=?',
        (min(read.remaining,512*1024),key)).fetchone()
    if row is None:return None
    if (any(row[n] is None for n in ('event_type','producer','object_id','payload_sha256','input_versions','payload')) or
            any(type(row[n]) is not int for n in ('seq','previous_state_version','new_state_version','object_version'))):
        raise Conflict('condition acceptance bounded original header differs')
    # Same cumulative envelope covers original header, blob expansion and JSON.
    read.charge_literal(dict(row));payload=read.parse(row['payload'].encode())
    if (type(payload) is not dict or canonical(payload).decode()!=row['payload'] or sha(payload)!=row['payload_sha256'] or
            set(payload)!={'format','put','delete','details'} or type(payload['format']) is not int or payload['format']!=2 or
            type(payload['put']) is not list or type(payload['delete']) is not list or
            payload['delete']!=[] or payload['details'] is not None):
        raise Conflict('condition acceptance original event integrity differs')
    rows=[];markers=[];seen=set()
    for item in payload['put']:
        if (type(item) is not list or len(item)!=3 or item[0]!=SECTION or
                type(item[1]) is not str or item[1] in seen):
            raise Conflict('condition acceptance original descriptor differs')
        seen.add(item[1]);v=read.decode(item[2]);(rows if item[1] else markers).append((item[1],v) if item[1] else v)
    prior=db.execute('SELECT 1 FROM events WHERE event_type=? AND seq<? LIMIT 1',(EVENT,row['seq'])).fetchone()
    if len(rows)!=1 or rows[0][0]!=key or markers!=([{}] if prior is None else []):
        raise Conflict('condition acceptance original mutation differs')
    value=rows[0][1];validate_record(key,value);version=value['accepted_state_version']
    if (row['event_type']!=EVENT or row['producer']!='hybrid-core' or row['object_id']!=digest(value) or
            any(row[k]!=version for k in ('seq','new_state_version','object_version')) or
            row['previous_state_version']!=version-1 or row['input_versions']!=canonical(event_inputs(value)).decode()):
        raise Conflict('condition acceptance original header/inputs differ')
    return value


def validate_persisted(state):
    for key,value in state.get(SECTION,{}).items():validate_record(key,value)


def validate_complete(state,registration,event_lookup,event_count):
    validate_persisted(state);facts=state.get(SECTION,{})
    if len(facts)!=event_count or (SECTION in state)!=(event_count>0):
        raise Conflict('condition acceptance domain differs from original events')
    for key,value in facts.items():
        if (value['accepted_state_version']>state['version'] or
                registration!=(value['request']['project_id'],value['request']['data_mode']) or event_lookup(key)!=value):
            raise Conflict('condition acceptance historical event differs')
        validate_links(value,lambda s,k:state.get(s,{}).get(k))
