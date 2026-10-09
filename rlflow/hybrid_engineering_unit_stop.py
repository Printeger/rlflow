"""Human emergency intent acceptance is not a Runtime STOP/FREE proof.

Separate immutable intent lets original safety cleanup finish before acceptance
without backfilling, rewriting or blocking the original Runtime lifecycle.
"""
from .hybrid_protocol import ID, HASH, TIME, obj, validate_schema
from .hybrid_goals import digest, check_bytes
from .hybrid_fixture_runtime_ledger import control_command_id
from .hybrid_engineering_patch import KIND
from .hybrid_budget_ledger import SECTIONS as BUDGET, validate_record as budget_record
from .store import Conflict

SECTION = 'hybrid_engineering_unit_stops'
EVENT = 'HYBRID_ENGINEERING_UNIT_STOP_ACCEPTED'
COUNT = {'type':'integer','minimum':0,'maximum':2**63-1}
BODY = obj({'action':{'const':'CANCEL_FIXED_ENGINEERING'},'task_id':ID})
REQUEST = obj({**BODY['properties'],'project_id':ID,'data_mode':{'const':'fixture'},
    'store_epoch':ID,'actor_id':ID,'idempotency_key':ID})
FACT = obj({'schema_version':{'const':'1.0'},'request':REQUEST,'request_hash':HASH,
    'registration_key':ID,'registration_hash':HASH,'acceptance_expected_state_version':COUNT,
    'accepted_state_version':{**COUNT,'minimum':1},'recorded_at':TIME})


def fact_key(request):
    # Same namespace as original RUN/HANDOFF, deliberately not action/task.
    return control_command_id(request,request['actor_id'],request['idempotency_key'])


def validate_record(key,value):
    check_bytes(value,4096); validate_schema(FACT,value)
    request=value['request']; body={k:request[k] for k in BODY['properties']}
    if (key!=fact_key(request) or value['request_hash']!=digest(body) or
            value['accepted_state_version']!=value['acceptance_expected_state_version']+1):
        raise Conflict('engineering emergency intent immutable identity differs')


def validate_links(value,lookup):
    registration=lookup(BUDGET[0],value['registration_key'])
    if registration is None: raise Conflict('engineering stop original registration missing')
    budget_record(BUDGET[0],value['registration_key'],registration)
    source=registration['request']; runtime=source.get('fixture_runtime',{})
    request=value['request']; origin=runtime.get('origin',{})
    if (runtime.get('phase')!='REGISTER_NO_HANDOFF' or origin.get('kind')!=KIND or
            digest(registration)!=value['registration_hash'] or origin.get('task_id')!=request['task_id'] or
            any(source[k]!=request[k] for k in ('project_id','data_mode','store_epoch')) or
            registration['accepted_state_version']>=value['accepted_state_version']):
        raise Conflict('engineering stop original registration scope differs')


def event_inputs(value):
    return {k:value[k] for k in ('registration_key','registration_hash')}


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
            type(payload['format']) is not int or payload['format']!=2 or payload['delete']!=[] or
            payload['details'] is not None or type(payload['put']) is not list):
        raise Conflict('closed engineering stop intent append required')
    marker=[] if lookup(SECTION,'') is not None else [[SECTION,'',{}]]
    rows=payload['put']
    if (len(rows)!=len(marker)+1 or rows[:-1]!=marker or
            type(rows[-1]) is not list or len(rows[-1])!=3 or rows[-1][:2]!=[SECTION,key]):
        raise Conflict('single engineering stop immutable intent required')
    value=rows[-1][2]; validate_record(key,value); validate_links(value,lookup)
    if (lookup(SECTION,key) is not None or event_type!=EVENT or object_id!=digest(value) or
            producer!='hybrid-core' or version!=value['accepted_state_version'] or
            registration!=(value['request']['project_id'],value['request']['data_mode'])):
        raise Conflict('engineering stop original accepting event differs')


def validate_persisted(state):
    rows=state.get(SECTION)
    if rows is None:return
    if type(rows) is not dict:raise Conflict('engineering stop intent section must be object')
    for key,value in rows.items():
        validate_record(key,value)


def validate_complete(state,registration,source,source_count):
    rows=state.get(SECTION,{})
    if len(rows)!=source_count:
        raise Conflict('engineering stop intent source coverage differs')
    if not rows:return
    # Physical empty-key marker initializes this map; replay/snapshot state
    # contains only its actual members. Whole source proof checks the marker.
    for key,value in rows.items():
        validate_record(key,value);validate_links(value,lambda s,k:state.get(s,{}).get(k))
        if (registration!=(value['request']['project_id'],value['request']['data_mode']) or
                value['accepted_state_version']>state['version'] or
                source(key)!=((EVENT,'hybrid-core',digest(value),value['accepted_state_version']),
                              [(SECTION,key,digest(value))])):
            raise Conflict('engineering stop intent complete original source differs')
