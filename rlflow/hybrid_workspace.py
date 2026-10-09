"""Closed historical workspace facts; no FD adoption or execution authority.

Under construction: pure validation is not yet wired into Store or an actual
WorkspaceService. Only the later fixed owner may attest physical close success.
"""
from datetime import timedelta

from .hybrid_protocol import ID,HASH,TIME,obj,enum,array,validate_schema
from .hybrid_goals import digest,check_bytes
from .hybrid_authority import timestamp
from .hybrid_preparation import (SOURCES,SECTIONS as PREPARATION,_references,
    _intent_links,_result_links,validate_record as preparation_record)
from .hybrid_admission import PREPARATION_REF,CONTROLLER_REF
from .hybrid_controller import (PROCESS,SECTIONS as CONTROLLER,fact_key as controller_key,
    head as controller_head,scope_key as controller_scope,validate_record as controller_record)
from .hybrid_budget_ledger import (HEADS as BUDGET_HEADS,SECTIONS as BUDGET,
    derived_heads as budget_heads,validate_record as budget_record,validate_links as budget_links)
from .store import Conflict,sha

SECTIONS=('hybrid_workspace_facts','hybrid_workspace_heads','hybrid_workspace_claims')
EVENT='HYBRID_WORKSPACE_RECORDED'
COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
POSITIVE={**COUNT,'minimum':1}
IDENTITY={**array({'type':'integer','minimum':0,'maximum':2**64-1},3),'minItems':3}
KERNEL=obj({'directory_identity':IDENTITY,'parent_identity':IDENTITY,'owner':PROCESS,
    'filesystem':enum('btrfs','ext4','tmpfs','xfs'),'execution_enabled':{'const':False}})
OBSERVATION=obj({'workspace_id':ID,'base_snapshot_id':ID,'base_snapshot_hash':HASH,
    'initial_copy_hash':HASH,'output_snapshot_hash':{'type':'null'},'kernel':KERNEL,
    'state':{'const':'HELD_PRE_RUNTIME'},'observation_id':ID,'epoch':POSITIVE,
    'checked_at':TIME,'expires_at':TIME,'execution_enabled':{'const':False},'release_enabled':{'const':False}})
CLOSE_SUCCESS=obj({'witness_id':ID,'workspace_id':ID,'observation_id':ID,'observation_hash':HASH,
    'kernel':KERNEL,'state':{'const':'CLOSED_PRE_RUNTIME'},'execution_enabled':{'const':False},
    'release_enabled':{'const':False}})
COMMON={'project_id':ID,'data_mode':enum('live','fixture'),'goal_ref':ID,'store_epoch':ID,
    'idempotency_key':ID,'expected_state_version':COUNT,'expected_workspace_revision':COUNT,
    'workspace_id':ID,'reservation_id':ID}
REQUEST={'oneOf':[obj({**COMMON,'operation':enum('acquire','renew'),
    'ttl_seconds':{'type':'integer','minimum':1,'maximum':60}}),
    obj({**COMMON,'operation':enum('request_close','complete_close')})]}
STATE=enum('HELD_PRE_RUNTIME','CLOSE_REQUESTED','CLOSED_PRE_RUNTIME')
HEAD=obj({'project_id':ID,'data_mode':enum('live','fixture'),'goal_ref':ID,'store_epoch':ID,
    'workspace_id':ID,'reservation_id':ID,'revision':POSITIVE,'state':STATE,
    'fact_key':ID,'fact_hash':HASH,'accepted_state_version':POSITIVE,
    'execution_enabled':{'const':False},'release_enabled':{'const':False}})
CLAIM=obj({'project_id':ID,'data_mode':enum('live','fixture'),'goal_ref':ID,
    'workspace_id':ID,'reservation_id':ID,'origin_fact_key':ID,'origin_fact_hash':HASH,
    'accepted_state_version':POSITIVE,'execution_enabled':{'const':False}})
FACT=obj({'request':REQUEST,'request_hash':HASH,'sources':SOURCES,'preparation':PREPARATION_REF,
    'budget_reservation':BUDGET_HEADS[1],'controller':CONTROLLER_REF,
    'observation':OBSERVATION,'observation_issued_monotonic_ns':COUNT,
    'observation_expires_monotonic_ns':POSITIVE,'controller_checked_monotonic_ns':COUNT,
    'physical_close':{'oneOf':[CLOSE_SUCCESS,{'type':'null'}]},
    'recorded_at':TIME,'prior_head':{'oneOf':[HEAD,{'type':'null'}]},'state':STATE,
    'accepted_state_version':POSITIVE,'execution_enabled':{'const':False},'release_enabled':{'const':False}})


def fact_key(request):
    return 'workspace_fact_'+sha([request['project_id'],request['data_mode'],request['idempotency_key']])


def head_key(request):
    # One immutable reservation lineage: close does not permit reusing it for
    # another workspace. New work needs a new actual budget reservation.
    return 'workspace_reservation_'+sha([request['project_id'],request['data_mode'],request['reservation_id']])


def claim_key(request):
    return 'workspace_claim_'+sha([request['project_id'],request['data_mode'],request['workspace_id']])


def claim(value):
    request=value['request']
    return {**{n:request[n] for n in ('project_id','data_mode','goal_ref','workspace_id','reservation_id')},
        'origin_fact_key':fact_key(request),'origin_fact_hash':digest(value),
        'accepted_state_version':value['accepted_state_version'],'execution_enabled':False}


def head(value):
    request=value['request']
    return {**{n:request[n] for n in ('project_id','data_mode','goal_ref','store_epoch','workspace_id','reservation_id')},
        'revision':request['expected_workspace_revision']+1,'state':value['state'],
        'fact_key':fact_key(request),'fact_hash':digest(value),'accepted_state_version':value['accepted_state_version'],
        'execution_enabled':False,'release_enabled':False}


def validate_record(section,key,value):
    if section not in SECTIONS:raise Conflict('unknown workspace section')
    check_bytes(value,64*1024)
    validate_schema((FACT,HEAD,CLAIM)[SECTIONS.index(section)],value)
    integers=[]
    if section==SECTIONS[0]:
        request=value['request'];observation=value['observation'];operation=request['operation']
        prior=value['prior_head'];expected={'acquire':'HELD_PRE_RUNTIME','renew':'HELD_PRE_RUNTIME',
            'request_close':'CLOSE_REQUESTED','complete_close':'CLOSED_PRE_RUNTIME'}[operation]
        duration=timestamp(observation['expires_at'])-timestamp(observation['checked_at'])
        mono_duration=value['observation_expires_monotonic_ns']-value['observation_issued_monotonic_ns']
        if (key!=fact_key(request) or value['request_hash']!=digest(request) or value['state']!=expected or
                value['accepted_state_version']!=request['expected_state_version']+1 or
                observation['workspace_id']!=request['workspace_id'] or
                timestamp(value['recorded_at'])<timestamp(observation['checked_at']) or
                not 10**9<=mono_duration<=60*10**9 or mono_duration%10**9 or
                duration!=timedelta(seconds=mono_duration//10**9)):
            raise Conflict('workspace fact identity or lifetime differs')
        if operation in ('acquire','renew'):
            if (duration!=timedelta(seconds=request['ttl_seconds']) or
                    not timestamp(value['recorded_at'])<timestamp(observation['expires_at'])):
                raise Conflict('workspace live observation TTL differs')
            integers.append(request['ttl_seconds'])
        if operation=='acquire':
            if prior is not None or request['expected_workspace_revision']!=0 or observation['epoch']!=1:
                raise Conflict('workspace acquire cannot adopt a prior lineage')
        else:
            if prior is None:raise Conflict('workspace transition requires original predecessor')
            validate_record(SECTIONS[1],head_key(request),prior)
            if (any(prior[n]!=request[n] for n in ('project_id','data_mode','goal_ref','workspace_id','reservation_id')) or
                    prior['revision']!=request['expected_workspace_revision'] or
                    prior['accepted_state_version']>=value['accepted_state_version'] or
                    prior['state']!=('CLOSE_REQUESTED' if operation=='complete_close' else 'HELD_PRE_RUNTIME')):
                raise Conflict('workspace predecessor scope or state differs')
        closed=value['physical_close']
        if operation=='complete_close':
            if (closed is None or closed['workspace_id']!=request['workspace_id'] or
                    closed['observation_id']!=observation['observation_id'] or
                    closed['observation_hash']!=digest(observation) or closed['kernel']!=observation['kernel']):
                raise Conflict('workspace original physical-close binding differs')
        elif closed is not None:raise Conflict('workspace physical-close proof before completion refused')
        integers.extend([request['expected_state_version'],request['expected_workspace_revision'],
            value['accepted_state_version'],value['observation_issued_monotonic_ns'],
            value['observation_expires_monotonic_ns'],value['controller_checked_monotonic_ns'],observation['epoch'],
            *observation['kernel']['directory_identity'],*observation['kernel']['parent_identity'],
            observation['kernel']['owner']['pid'],observation['kernel']['owner']['pgid']])
    elif section==SECTIONS[1]:
        if key!=head_key(value):raise Conflict('workspace head identity differs')
        integers.extend([value['revision'],value['accepted_state_version']])
    else:
        if key!=claim_key(value):raise Conflict('workspace immutable claim identity differs')
        integers.append(value['accepted_state_version'])
    if any(type(n) is not int for n in integers):raise Conflict('actual workspace integers required')


def validate_links(value,lookup,*,current=False):
    request=value['request'];operation=request['operation'];sources=value['sources'];observation=value['observation']
    live=operation in ('acquire','renew')
    if (any(sources[n]!=request[n] for n in ('project_id','data_mode','goal_ref')) or
            sources['source_version']>request['expected_state_version']):
        raise Conflict('workspace source scope differs')
    _references(sources,lookup,current=current and live)
    if live and (sources['store_epoch']!=request['store_epoch'] or
            sources['source_version']!=request['expected_state_version'] or
            not timestamp(sources['evaluated_at'])<=timestamp(value['recorded_at'])<timestamp(sources['expires_at'])):
        raise Conflict('workspace current original consent differs')
    if live and not value['observation_issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<value['observation_expires_monotonic_ns']:
        raise Conflict('workspace capture lies outside actual observation elapsed deadline')
    original_claim=lookup(SECTIONS[2],claim_key(request))
    if operation=='acquire':
        if current and original_claim is not None or not current and original_claim is not None and original_claim!=claim(value):
            raise Conflict('workspace identity was already claimed')
    else:
        if original_claim is None:raise Conflict('workspace original immutable claim missing')
        validate_record(SECTIONS[2],claim_key(request),original_claim)
        acquired=lookup(SECTIONS[0],original_claim['origin_fact_key'])
        if (acquired is None or acquired['request']['operation']!='acquire' or claim(acquired)!=original_claim or
                any(original_claim[n]!=request[n] for n in ('project_id','data_mode','goal_ref','workspace_id','reservation_id'))):
            raise Conflict('workspace identity cannot bind a different reservation')
    reservation=value['budget_reservation'];rid=request['reservation_id']
    budget_record(BUDGET[2],rid,reservation)
    original=lookup(BUDGET[0],reservation['last_entry_key'])
    if original is not None:
        budget_record(BUDGET[0],reservation['last_entry_key'],original)
        budget_links(original,lookup)
    if (original is None or budget_heads(original)[BUDGET[2]].get(rid)!=reservation or
            reservation['status']!='HELD' or reservation['runtime_registration']!='NOT_AUTHORIZED' or
            any(reservation['scope'][n]!=request[n] for n in ('project_id','data_mode','goal_ref')) or
            any(sources[n]!=v for n,v in reservation['origin_sources'].items() if n not in ('source_version','evaluated_at')) or
            reservation['preparation']!=value['preparation'] or
            reservation['accepted_state_version']>=value['accepted_state_version']):
        raise Conflict('workspace original PRE_RUNTIME budget head differs')
    if current and live and lookup(BUDGET[2],rid)!=reservation:
        raise Conflict('workspace current reservation no longer exact HELD')
    ref=value['preparation'];intent=lookup(PREPARATION[0],ref['intent_key']);outcome=lookup(PREPARATION[1],ref['result_key'])
    if intent is not None:preparation_record(PREPARATION[0],ref['intent_key'],intent);_intent_links(intent,lookup)
    if outcome is not None and intent is not None:
        preparation_record(PREPARATION[1],ref['result_key'],outcome);_result_links(outcome,intent,lookup)
    if (intent is None or outcome is None or outcome['status']!='PREPARED' or
            ref['intent_hash']!=digest(intent) or ref['result_hash']!=digest(outcome) or
            observation['base_snapshot_id']!=intent['snapshot_id'] or
            observation['base_snapshot_hash']!=intent['snapshot']['tree_hash'] or
            observation['initial_copy_hash']!=digest([{**row,'source_executable':False} for row in intent['snapshot']['files']]) or
            any(sources[n]!=v for n,v in intent['sources'].items() if n not in ('source_version','evaluated_at'))):
        raise Conflict('workspace original preparation or consent differs')
    prior=value['prior_head']
    if prior is not None:
        previous=lookup(SECTIONS[0],prior['fact_key'])
        if previous is None or head(previous)!=prior:raise Conflict('workspace original predecessor missing')
        old=previous['observation']
        if timestamp(value['recorded_at'])<timestamp(previous['recorded_at']):raise Conflict('workspace historical clock regressed')
        if operation=='renew':
            stable=lambda obs:{n:v for n,v in obs.items() if n not in ('observation_id','epoch','checked_at','expires_at')}
            if (stable(old)!=stable(observation) or observation['epoch']!=old['epoch']+1 or
                    not timestamp(old['checked_at'])<=timestamp(observation['checked_at'])<timestamp(old['expires_at']) or
                    not previous['observation_issued_monotonic_ns']<=value['observation_issued_monotonic_ns']<previous['observation_expires_monotonic_ns']):
                raise Conflict('workspace renewal changes or expires actual held lineage')
        elif (observation!=old or value['sources']!=previous['sources'] or
                value['budget_reservation']!=previous['budget_reservation'] or
                value['preparation']!=previous['preparation'] or
                any(value[n]!=previous[n] for n in ('observation_issued_monotonic_ns','observation_expires_monotonic_ns'))):
            raise Conflict('workspace close cannot replace original held binding')
    if current and lookup(SECTIONS[1],head_key(request))!=prior:
        raise Conflict('workspace current prior head changed')
    cr=value['controller'];control=lookup(CONTROLLER[0],cr['fact_key'])
    if control is None:raise Conflict('workspace original controller missing')
    controller_record(CONTROLLER[0],cr['fact_key'],control)
    if (cr!={'fact_key':controller_key(control['request']),'fact_hash':digest(control),
            'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            any(control['request'][n]!=request[n] for n in ('project_id','data_mode','store_epoch')) or
            observation['kernel']['owner']!=control['request']['owner']['process'] or
            control['accepted_state_version']>=value['accepted_state_version'] or
            not timestamp(control['issued_at'])<=timestamp(value['recorded_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns'] or
            live and control['config_hash']!=sources['config_hash']):
        raise Conflict('workspace original controller capture differs')
    if current and lookup(CONTROLLER[1],controller_scope(request['project_id'],request['data_mode']))!=controller_head(control):
        raise Conflict('workspace controller is not current')


def expected_objects(value):
    result=[(SECTIONS[0],fact_key(value['request']),digest(value)),
        (SECTIONS[1],head_key(value['request']),digest(head(value)))]
    if value['request']['operation']=='acquire':result.append((SECTIONS[2],claim_key(value['request']),digest(claim(value))))
    return sorted(result)


def event_inputs(value):
    return {'workspace_fact_hash':digest(value),'workspace_reservation_id':value['request']['reservation_id']}


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
            type(payload['format']) is not int or payload['format']!=2 or type(payload['put']) is not list or
            type(payload['delete']) is not list or payload['delete'] or payload['details'] is not None):
        raise Conflict('closed workspace append transaction required')
    rows={};markers={}
    for row in payload['put']:
        if type(row) is not list or len(row)!=3 or not all(type(v) is str for v in row[:2]):
            raise Conflict('workspace original descriptor invalid')
        section,objkey,value=row
        if section not in SECTIONS or (section,objkey) in rows or not objkey and section in markers:
            raise Conflict('workspace extra or duplicate object')
        if not objkey:markers[section]=value
        else:rows[(section,objkey)]=value
    facts=[(k,v) for (s,k),v in rows.items() if s==SECTIONS[0]]
    if len(facts)!=1:raise Conflict('exact one immutable workspace fact required')
    fk,value=facts[0];validate_record(SECTIONS[0],fk,value);request=value['request']
    expected={(SECTIONS[0],fk):value,(SECTIONS[1],head_key(request)):head(value)}
    if request['operation']=='acquire':expected[(SECTIONS[2],claim_key(request))]=claim(value)
    if (rows!=expected or
            markers!={s:{} for s in SECTIONS if lookup(s,'') is None} or lookup(SECTIONS[0],fk) is not None or
            event_type!=EVENT or key!=fk or object_id!=request['reservation_id'] or producer!='hybrid-core' or
            version!=value['accepted_state_version'] or registration!=(request['project_id'],request['data_mode'])):
        raise Conflict('workspace exact original event/head differs')
    validate_links(value,lookup,current=True)


def validate_persisted(state):
    for section in SECTIONS:
        for key,value in state.get(section,{}).items():validate_record(section,key,value)


def validate_complete(state,registration=None,event_lookup=None,*,event_summary=(None,0)):
    validate_persisted(state);facts=state.get(SECTIONS[0],{});derived={};claims={}
    lookup=lambda s,k:state.get(s,{}).get(k)
    ordered=sorted(facts.items(),key=lambda item:item[1]['accepted_state_version'])
    for fk,value in ordered:
        request=value['request'];hk=head_key(request)
        if (value['accepted_state_version']>state['version'] or registration!=(request['project_id'],request['data_mode']) or
                event_lookup is None or event_lookup(fk)!=((EVENT,'hybrid-core',request['reservation_id'],value['accepted_state_version']),expected_objects(value)) or
                value['prior_head']!=derived.get(hk)):
            raise Conflict('workspace original source/history differs')
        if request['operation']=='acquire':
            ck=claim_key(request)
            if ck in claims:raise Conflict('workspace history reuses an immutable claimed identity')
            claims[ck]=claim(value)
        validate_links(value,lookup);derived[hk]=head(value)
    if state.get(SECTIONS[1],{})!=derived:raise Conflict('workspace historical heads differ')
    if state.get(SECTIONS[2],{})!=claims:raise Conflict('workspace historical immutable claims differ')
    latest=ordered[-1] if ordered else None
    if event_summary!=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(facts)):
        raise Conflict('workspace historical domain differs from original tip/count')
