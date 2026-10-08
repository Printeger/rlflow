"""Pure Hybrid core-fact controller fencing; never an ExecutionLease.

Historical validation uses recorded predecessors, not today's kernel or clock.
The actual owner, live deadlines and legacy-domain exclusion belong to the fixed
service/Store boundary. This domain alone does not prove workspace exclusivity.
"""
from datetime import timedelta

from .hybrid_authority import timestamp
from .hybrid_goals import digest, check_bytes
from .hybrid_protocol import ID, HASH, TIME, obj, enum, validate_schema
from .store import Conflict, sha

SECTIONS=('hybrid_controller_facts','hybrid_controller_heads')
EVENT='HYBRID_CONTROLLER_RECORDED'
COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
POSITIVE={**COUNT,'minimum':1}
PROCESS=obj({'pid':{**POSITIVE,'maximum':2**31-1},'pgid':{**POSITIVE,'maximum':2**31-1},
    'starttime':{'type':'string','pattern':'^[0-9]{1,30}$'},'boot_id':ID})
OWNER=obj({'id':ID,'process':PROCESS})
REQUEST=obj({'authority_domain':{'const':'HYBRID_CORE_FACTS_ONLY'},'project_id':ID,
    'data_mode':enum('live','fixture'),'store_epoch':ID,'owner':OWNER,
    'operation':enum('acquire','renew'),'idempotency_key':ID,
    'ttl_seconds':{'type':'integer','minimum':1,'maximum':60},'expected_state_version':COUNT,
    'expected_head_revision':COUNT,'previous_fact_key':{'oneOf':[ID,{'type':'null'}]},
    'previous_fact_hash':{'oneOf':[HASH,{'type':'null'}]}})
FACT=obj({'request':REQUEST,'request_hash':HASH,'config_hash':HASH,
    'controller_epoch':POSITIVE,'head_revision':POSITIVE,'issued_at':TIME,'expires_at':TIME,
    'issued_monotonic_ns':COUNT,'expires_monotonic_ns':POSITIVE,
    'accepted_state_version':POSITIVE,'reason':enum('INITIAL','RENEWED','EXPIRED_PREDECESSOR','NEW_STORE_EPOCH'),
    'prior_runtime_recovery':{'const':'UNVERIFIED'},'candidate_write_enabled':{'const':False},
    'execution_enabled':{'const':False}})
HEAD=obj({'project_id':ID,'data_mode':enum('live','fixture'),'store_epoch':ID,
    'controller_epoch':POSITIVE,'revision':POSITIVE,'fact_key':ID,'fact_hash':HASH,
    'execution_enabled':{'const':False}})


def scope_key(project_id,data_mode):
    return 'controller_scope_'+sha([project_id,data_mode])


def fact_key(request):
    return 'controller_fact_'+sha([request['project_id'],request['data_mode'],request['store_epoch'],
        request['owner']['id'],request['idempotency_key']])


def head(value):
    request=value['request']
    return {'project_id':request['project_id'],'data_mode':request['data_mode'],
        'store_epoch':request['store_epoch'],'controller_epoch':value['controller_epoch'],
        'revision':value['head_revision'],'fact_key':fact_key(request),'fact_hash':digest(value),
        'execution_enabled':False}


def validate_record(section,key,value):
    if section not in SECTIONS:raise Conflict('unknown controller section')
    check_bytes(value,64*1024);validate_schema(FACT if section==SECTIONS[0] else HEAD,value)
    if section==SECTIONS[0]:
        request=value['request']
        if (key!=fact_key(request) or value['request_hash']!=digest(request) or
                value['accepted_state_version']!=request['expected_state_version']+1 or
                value['head_revision']!=request['expected_head_revision']+1 or
                timestamp(value['expires_at'])-timestamp(value['issued_at'])!=timedelta(seconds=request['ttl_seconds']) or
                value['expires_monotonic_ns']-value['issued_monotonic_ns']!=request['ttl_seconds']*10**9 or
                (request['previous_fact_key'] is None)!=(request['previous_fact_hash'] is None)):
            raise Conflict('controller fact identity or lifetime differs')
        integers=[request['ttl_seconds'],request['expected_state_version'],request['expected_head_revision'],
                  request['owner']['process']['pid'],request['owner']['process']['pgid'],
                  value['controller_epoch'],value['head_revision'],value['accepted_state_version'],
                  value['issued_monotonic_ns'],value['expires_monotonic_ns']]
    else:
        if key!=scope_key(value['project_id'],value['data_mode']):raise Conflict('controller head scope differs')
        integers=[value['controller_epoch'],value['revision']]
    if any(type(v) is not int for v in integers):raise Conflict('actual controller integers required')


def validate_persisted(state):
    for section in SECTIONS:
        for key,value in state.get(section,{}).items():validate_record(section,key,value)


def _predecessor(value,lookup):
    request=value['request'];key=request['previous_fact_key']
    if key is None:
        if (request['operation']!='acquire' or value['reason']!='INITIAL' or
                request['expected_head_revision']!=0 or value['controller_epoch']!=1):
            raise Conflict('initial controller predecessor differs')
        return None
    previous=lookup(SECTIONS[0],key)
    if previous is None or digest(previous)!=request['previous_fact_hash']:
        raise Conflict('controller original predecessor missing')
    old=previous['request']
    if (any(old[n]!=request[n] for n in ('project_id','data_mode')) or
            previous['head_revision']!=request['expected_head_revision'] or
            previous['accepted_state_version']>=value['accepted_state_version'] or
            timestamp(previous['issued_at'])>timestamp(value['issued_at'])):
        raise Conflict('controller predecessor lineage differs')
    if request['operation']=='renew':
        if (request['owner']!=old['owner'] or request['store_epoch']!=old['store_epoch'] or
                value['config_hash']!=previous['config_hash'] or value['reason']!='RENEWED' or
                value['controller_epoch']!=previous['controller_epoch'] or
                not previous['issued_monotonic_ns']<=value['issued_monotonic_ns']<previous['expires_monotonic_ns'] or
                timestamp(value['issued_at'])>=timestamp(previous['expires_at'])):
            raise Conflict('controller renewal changes or expires ownership')
    elif (value['controller_epoch']!=previous['controller_epoch']+1 or
            (request['store_epoch']!=old['store_epoch'] and value['reason']!='NEW_STORE_EPOCH') or
            (request['store_epoch']==old['store_epoch'] and
             (value['reason']!='EXPIRED_PREDECESSOR' or timestamp(value['issued_at'])<timestamp(previous['expires_at'])))):
        raise Conflict('controller takeover lacks a new fence')
    if (request['operation']=='acquire' and request['store_epoch']==old['store_epoch'] and
            (request['owner']['process']['boot_id']!=old['owner']['process']['boot_id'] or
             value['issued_monotonic_ns']<previous['expires_monotonic_ns'])):
        raise Conflict('controller takeover lacks boot-bound elapsed deadline')
    return previous


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (set(payload)!={'format','put','delete','details'} or type(payload.get('format')) is not int or payload['format']!=2 or
            payload['details'] is not None or type(payload.get('put')) is not list or
            type(payload.get('delete')) is not list or payload['delete']):
        raise Conflict('controller requires closed append-and-head transaction')
    rows={};seen=set()
    for row in payload['put']:
        if type(row) is not list or len(row)!=3 or not all(type(v) is str for v in row[:2]):
            raise Conflict('controller descriptor invalid')
        section,objkey,value=row
        if section not in SECTIONS or (section,objkey) in seen:raise Conflict('controller extra or duplicate mutation')
        seen.add((section,objkey))
        if not objkey:
            if value!={} or lookup(section,'') is not None:raise Conflict('controller marker differs')
        else:
            if section in rows:raise Conflict('controller single fact and head required')
            validate_record(section,objkey,value);rows[section]=(objkey,value)
    if set(rows)!=set(SECTIONS):raise Conflict('controller fact/head pair missing')
    fk,value=rows[SECTIONS[0]];hk,current=rows[SECTIONS[1]];request=value['request']
    if (event_type!=EVENT or key!=fk or object_id!=digest(value) or producer!='hybrid-core' or
            value['accepted_state_version']!=version or registration!=(request['project_id'],request['data_mode']) or
            lookup(SECTIONS[0],fk) is not None or current!=head(value)):
        raise Conflict('controller event binding differs')
    previous=_predecessor(value,lookup);old_head=lookup(SECTIONS[1],hk)
    markers={s for s,k in seen if not k}
    if markers!=(set(SECTIONS) if previous is None else set()):
        raise Conflict('controller original collection markers differ')
    if previous is None and any(lookup(section,'') is not None for section in SECTIONS):
        raise Conflict('initial controller cannot reset existing collections')
    if old_head!=(None if previous is None else head(previous)):
        raise Conflict('controller current head changed')


def validate_complete(state,registration=None,event_lookup=None,*,event_tip=None):
    validate_persisted(state);lookup=lambda s,k:state.get(s,{}).get(k)
    latest={};revisions=set()
    for key,value in state.get(SECTIONS[0],{}).items():
        request=value['request'];hk=scope_key(request['project_id'],request['data_mode']);current=head(value)
        if (registration!=(request['project_id'],request['data_mode']) or
                value['accepted_state_version']>state['version'] or event_lookup is None or event_lookup(key)!=(
                    (EVENT,'hybrid-core',digest(value),value['accepted_state_version']),
                    sorted([(SECTIONS[0],key,digest(value)),(SECTIONS[1],hk,digest(current))]))):
            raise Conflict('controller original event proof differs')
        _predecessor(value,lookup)
        if (hk,value['head_revision']) in revisions:raise Conflict('controller history forks')
        revisions.add((hk,value['head_revision']))
        if hk not in latest or latest[hk]['revision']<current['revision']:latest[hk]=current
    if state.get(SECTIONS[1],{})!=latest:raise Conflict('controller latest head differs from original lineage')
    if latest:
        tip=max(latest.values(),key=lambda h:state[SECTIONS[0]][h['fact_key']]['accepted_state_version'])
        expected_tip=(tip['fact_key'],state[SECTIONS[0]][tip['fact_key']]['accepted_state_version'])
        if event_tip!=expected_tip:raise Conflict('controller historical event tip differs')
    elif event_tip is not None:
        raise Conflict('controller historical domain omitted despite original events')
