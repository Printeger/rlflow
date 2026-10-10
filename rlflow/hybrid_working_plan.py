"""Pure immutable NONEXECUTING Working plan facts, not a live permission.

Store integration and actual owner guards are required separately. Historical
validation never reconstructs a Kernel hold, material witness or runtime grant.
"""
from pathlib import Path
import re

from .execution_adapter import PROFILE, PACKET
from .files import relative_name
from .hybrid_protocol import ID,HASH,TIME,obj,array,validate_schema
from .hybrid_goals import digest,check_bytes,SECTIONS as GOALS
from .hybrid_preparation import SOURCES,GATES,SECTIONS as PREPARATION,_references
from .hybrid_admission import PREPARATION_REF,CONTROLLER_REF
from .hybrid_workspace import (HEAD,CLAIM,OBSERVATION,COUNT,POSITIVE,SECTIONS as WORKSPACE,
    head as workspace_head,claim as workspace_claim,claim_key,head_key as workspace_head_key,
    validate_record as workspace_record,validate_links as workspace_links)
from .hybrid_controller import (SECTIONS as CONTROLLER,validate_record as controller_record,
    fact_key as controller_key,head as controller_head,scope_key)
from .hybrid_budget_ledger import HEADS as BUDGET_HEADS,SECTIONS as BUDGET
from .hybrid_runtime_installation import (CHAIN,TRIPLE,RAW_HASH,SECTIONS as INSTALLATION,
    validate_record as installation_record,validate_links as installation_links)
from .hybrid_authority import timestamp
from .store import Conflict,sha,canonical
from .hybrid_live_domain import PROFILE as LIVE_PROFILE


def _domains(schema):
    """Keep historical fixture bytes closed; live requires an explicit profile."""
    fields=schema['properties']
    return {'oneOf':[schema,obj({**fields,'data_mode':{'const':'live'},
        'domain_profile':{'const':LIVE_PROFILE}})]}

SECTIONS=('hybrid_working_plan_intents','hybrid_working_plan_results')
EVENTS=('HYBRID_WORKING_PLAN_INTENT','HYBRID_WORKING_PLAN_READY')
PATH={'type':'string','minLength':1,'maxLength':4096}
FILES=('plan.json','packet.json','result.schema.json','command-plan.json',
       'control/result.json.models.json','control/result.json.mcp.json')
BOOTSTRAP=obj({'intent_key':ID,'intent_hash':HASH,'publication_key':ID,'publication_hash':HASH,
    'expected_seal_hash':HASH,'project_id':ID,'data_mode':{'const':'fixture'},'store_epoch':ID,
    'installation_id':ID,'release_id':RAW_HASH})
BOOTSTRAP=_domains(BOOTSTRAP)
CONTEXT=obj({'project_id':ID,'data_mode':{'const':'fixture'},'store_epoch':ID,'sources':SOURCES,
    'preparation':PREPARATION_REF,'workspace_head':HEAD,'workspace_claim':CLAIM,
    'budget_reservation':BUDGET_HEADS[1],'controller':CONTROLLER_REF,'observation':OBSERVATION,
    'observation_issued_monotonic_ns':COUNT,'observation_expires_monotonic_ns':POSITIVE,'bootstrap':BOOTSTRAP})
CONTEXT=_domains(CONTEXT)
TREE=obj({'files':{**array(obj({'name':PATH,'bytes':{**COUNT,'maximum':256*1024**2},
    'sha256':HASH,'mode':{'const':0o600}}),4096),'minItems':1},
    'directories':{**array(PATH,4096),'minItems':1},'total_bytes':{**COUNT,'maximum':256*1024**2},
    'tree_hash':HASH,'execution_enabled':{'const':False}})
PLAN=obj({'schema_version':{'const':'1.0'},'adapter':{'const':'codex-exec'},'sources':CONTEXT,
    'packet':PACKET,'profile':PROFILE,'role_definition':{'type':'object'},'result_schema':{'type':'object'},
    'candidate':PATH,'working_tree':TREE,'write_roots':array(PATH,128),'allowed_tools':array(ID,128),
    'allowed_command_templates':array(ID,128),'gates':GATES,'execution_enabled':{'const':False},
    'release_enabled':{'const':False}})
MANIFEST=obj({'plan_hash':HASH,'files':obj(dict.fromkeys(FILES,HASH)),
    'execution_enabled':{'const':False},'release_enabled':{'const':False}})
SEAL=obj({'manifest':MANIFEST,'manifest_hash':HASH,'directory_identity':TRIPLE,'parent_chain':CHAIN,
    'file_lengths':obj(dict.fromkeys(FILES,{**COUNT,'maximum':16*1024**2}))})
BINDING=obj({'stage_path':PATH,'published_path':PATH})
COMMON={'project_id':ID,'data_mode':{'const':'fixture'},'store_epoch':ID,'goal_ref':ID,
    'plan_id':ID,'idempotency_key':ID,'expected_state_version':COUNT}
REQUESTS=(obj({**COMMON,'action':{'const':'prepare_working_plan'}}),
    obj({**COMMON,'action':{'const':'publish_working_plan'},'intent_key':ID,'intent_hash':HASH}))
REQUESTS=tuple(_domains(schema) for schema in REQUESTS)
BASE={'request_hash':HASH,'accepted_state_version':POSITIVE,'source_context':CONTEXT,
    'recorded_at':TIME,'controller_checked_monotonic_ns':COUNT,'execution_enabled':{'const':False},
    'release_enabled':{'const':False}}
RECORDS=(obj({**BASE,'request':REQUESTS[0],'plan':PLAN,'expected_seal':SEAL,'material_binding':BINDING,
    'state':{'const':'WORKING_PLAN_INTENT'}}),
    obj({**BASE,'request':REQUESTS[1],'plan_hash':HASH,'expected_seal_hash':HASH,'material_binding':BINDING,
    'state':{'const':'PLAN_READY_NONEXECUTING'}}))


def intent_key(request):
    return 'working_plan_intent_'+sha([request['project_id'],request['data_mode'],request['store_epoch'],request['plan_id']])


def result_key(request):
    return 'working_plan_ready_'+sha(intent_key(request))


def stable_context(value):
    # Explicit closed-context exception, not recursive dropping arbitrary keys.
    return {**value,'sources':{k:v for k,v in value['sources'].items() if k not in ('source_version','evaluated_at')}}


def event_inputs(value):
    context=value['source_context'];request=value['request']
    result={'working_plan_fact_hash':digest(value),
        'workspace_fact':[context['workspace_head']['fact_key'],context['workspace_head']['fact_hash']],
        'budget_entry':[context['budget_reservation']['last_entry_key'],context['budget_reservation']['last_entry_hash']],
        'controller_fact':[context['controller']['fact_key'],context['controller']['fact_hash']],
        'bootstrap_publication':[context['bootstrap']['publication_key'],context['bootstrap']['publication_hash']],
        'preparation_result':[context['preparation']['result_key'],context['preparation']['result_hash']]}
    if request['action']=='publish_working_plan':result['working_plan_intent']=[request['intent_key'],request['intent_hash']]
    return result


def expected_objects(section,key,value):return [(section,key,digest(value))]


def _path(value):
    path=Path(value)
    if (len(value.encode())>4096 or not path.is_absolute() or str(path)!=value or '..' in path.parts or '\x00' in value or
            len(path.parts)>64):raise Conflict('canonical concrete Working plan path required')
    return path


def _tree(value):
    names=[row['name'] for row in value['files']];directories=value['directories'];expected={'.'}
    for name in names+directories:
        if (name!='.' and ('\x00' in name or len(name.encode())>4000 or
                len(Path(name).parts)>(65 if name in names else 64) or
                any(len(part.encode())>255 for part in Path(name).parts))):
            raise Conflict('original Working tree name byte/depth bound differs')
    for name in names:
        relative_name(name)
        parent=Path(name).parent
        while str(parent)!='.':expected.add(str(parent));parent=parent.parent
    for name in directories:
        if name!='.':relative_name(name)
    # Empty actual directories may also be present; every ancestor is required.
    for name in directories:
        parent=Path(name).parent
        while str(parent)!='.':expected.add(str(parent));parent=parent.parent
    if (names!=sorted(set(names)) or directories!=sorted(set(directories)) or not expected<=set(directories) or
            set(names)&set(directories) or any(any(str(parent) in names for parent in Path(name).parents if str(parent)!='.') for name in names+directories)):
        raise Conflict('closed original Working tree names differ')
    unsigned={k:v for k,v in value.items() if k not in ('tree_hash','execution_enabled')}
    if (value['total_bytes']!=sum(row['bytes'] for row in value['files']) or digest(unsigned)!=value['tree_hash'] or
            sum(len(name.encode()) for name in names+directories if name!='.')>1024**2 or
            any(type(row['bytes']) is not int or type(row['mode']) is not int for row in value['files']) or
            type(value['total_bytes']) is not int):raise Conflict('original Working tree hash or bound differs')


def validate_record(section,key,value):
    if section not in SECTIONS:raise Conflict('unknown Working plan section')
    phase=SECTIONS.index(section);check_bytes(value,16*1024**2 if phase==0 else 128*1024)
    validate_schema(RECORDS[phase],value)
    request=value['request'];context=value['source_context'];sources=context['sources']
    if (key!=(intent_key(request) if phase==0 else result_key(request)) or value['request_hash']!=digest(request) or
            type(request['expected_state_version']) is not int or type(value['accepted_state_version']) is not int or
            value['accepted_state_version']!=request['expected_state_version']+1 or
            sources['source_version']!=request['expected_state_version'] or
            value['recorded_at']!=sources['evaluated_at'] or
            any(context[n]!=request[n] or sources[n]!=request[n] for n in ('project_id','data_mode','store_epoch')) or
            sources['goal_ref']!=request['goal_ref']):raise Conflict('Working plan source identity or CAS differs')
    if any(context['bootstrap'][n]!=request[n] for n in ('project_id','data_mode','store_epoch')):
        raise Conflict('Working plan original bootstrap domain differs')
    if request.get('domain_profile')!=context.get('domain_profile') or request.get('domain_profile')!=context['bootstrap'].get('domain_profile'):
        raise Conflict('Working plan explicit original domain profile differs')
    mono=value['controller_checked_monotonic_ns'];obs=context['observation']
    if (type(mono) is not int or not context['observation_issued_monotonic_ns']<=mono<context['observation_expires_monotonic_ns'] or
            not timestamp(obs['checked_at'])<=timestamp(value['recorded_at'])<timestamp(obs['expires_at']) or
            not timestamp(value['recorded_at'])<timestamp(sources['expires_at'])):
        raise Conflict('Working plan original capture expired')
    binding=value['material_binding'];published=_path(binding['published_path']);stage=_path(binding['stage_path'])
    if published.name!=request['plan_id'] or stage!=published.with_name('.preparing-'+request['plan_id']):
        raise Conflict('Working plan material paths differ')
    if phase:return
    plan=value['plan'];seal=value['expected_seal'];_tree(plan['working_tree']);_path(plan['candidate'])
    if stable_context(plan['sources'])!=stable_context(context):raise Conflict('Working plan original seed context changed')
    seed_sources=plan['sources']['sources']
    if (seed_sources['source_version']>request['expected_state_version'] or
            not timestamp(obs['checked_at'])<=timestamp(seed_sources['evaluated_at'])<=timestamp(value['recorded_at'])):
        raise Conflict('Working plan original seed as-of version/time differs')
    if (plan['packet']['candidate_snapshot_hash']!=plan['working_tree']['tree_hash'] or
            len(canonical(plan['packet']))>256*1024 or seal['manifest']['plan_hash']!=digest(plan) or
            seal['manifest_hash']!=digest(seal['manifest']) or
            sum(seal['file_lengths'].values())+len(canonical(seal['manifest']))>16*1024**2):
        raise Conflict('Working plan expected seal differs')
    for name,objvalue in (('plan.json',plan),('packet.json',plan['packet']),('result.schema.json',plan['result_schema'])):
        if seal['manifest']['files'][name]!=digest(objvalue) or seal['file_lengths'][name]!=len(canonical(objvalue)):
            raise Conflict('Working plan deterministic material bytes differ')
    integers=[*seal['directory_identity'],*seal['file_lengths'].values(),*[n for row in seal['parent_chain'] for n in row]]
    if any(type(n) is not int for n in integers):raise Conflict('actual Working plan seal integers required')
    if len(seal['parent_chain'])!=len(published.parent.parts):raise Conflict('Working plan original parent chain differs')


def _context_links(value,lookup,*,current=False):
    context=value['source_context'];sources=context['sources'];request=value['request']
    _references(sources,lookup,current=current)
    wh=context['workspace_head'];original=lookup(WORKSPACE[0],wh['fact_key'])
    claim=context['workspace_claim'];acquired=lookup(WORKSPACE[0],claim['origin_fact_key'])
    if original is None or acquired is None:raise Conflict('Working plan original workspace fact missing')
    workspace_record(WORKSPACE[0],wh['fact_key'],original);workspace_links(original,lookup)
    workspace_record(WORKSPACE[0],claim['origin_fact_key'],acquired)
    if (workspace_head(original)!=wh or wh['state']!='HELD_PRE_RUNTIME' or
            acquired['request']['operation']!='acquire' or workspace_claim(acquired)!=claim or
            lookup(WORKSPACE[2],claim_key(original['request']))!=claim or
            any(context[n]!=original[n] for n in ('preparation','budget_reservation','observation',
                'observation_issued_monotonic_ns','observation_expires_monotonic_ns')) or
            any(sources[n]!=v for n,v in original['sources'].items() if n not in ('source_version','evaluated_at')) or
            any(original['request'][n]!=request[n] for n in ('project_id','data_mode','store_epoch','goal_ref')) or
            original['accepted_state_version']>request['expected_state_version']):
        raise Conflict('Working plan captured workspace/claim/preparation/budget differs')
    budget=lookup(BUDGET[0],context['budget_reservation']['last_entry_key'])
    preparation=lookup(PREPARATION[1],context['preparation']['result_key'])
    if (budget is None or preparation is None or
            timestamp(value['recorded_at'])<max(timestamp(original['recorded_at']),timestamp(acquired['recorded_at']),
                timestamp(budget['recorded_at']),timestamp(preparation['recorded_at'])) or
            value['controller_checked_monotonic_ns']<original['controller_checked_monotonic_ns']):
        raise Conflict('Working plan source capture clock regressed')
    control_ref=context['controller'];control=lookup(CONTROLLER[0],control_ref['fact_key'])
    if control is None:raise Conflict('Working plan original controller missing')
    controller_record(CONTROLLER[0],control_ref['fact_key'],control)
    if (control_ref!={'fact_key':controller_key(control['request']),'fact_hash':digest(control),
            'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            any(control['request'][n]!=request[n] for n in ('project_id','data_mode','store_epoch')) or
            control['request']['owner']['process']!=context['observation']['kernel']['owner'] or
            control['config_hash']!=sources['config_hash'] or control['accepted_state_version']>request['expected_state_version'] or
            not timestamp(control['issued_at'])<=timestamp(value['recorded_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns']):
        raise Conflict('Working plan original controller capture differs')
    bootstrap=context['bootstrap'];intent=lookup(INSTALLATION[0],bootstrap['intent_key']);ready=lookup(INSTALLATION[1],bootstrap['publication_key'])
    if intent is None or ready is None:raise Conflict('Working plan original bootstrap missing')
    installation_record(INSTALLATION[0],bootstrap['intent_key'],intent)
    installation_record(INSTALLATION[1],bootstrap['publication_key'],ready);installation_links(ready,lookup)
    if (bootstrap['intent_hash']!=digest(intent) or bootstrap['publication_hash']!=digest(ready) or
            bootstrap['expected_seal_hash']!=digest(intent['expected_seal']) or bootstrap['release_id']!=ready['release_id'] or
            any(bootstrap[n]!=intent['request'][n] for n in ('project_id','data_mode','store_epoch','installation_id')) or
            any(bootstrap[n]!=request[n] for n in ('project_id','data_mode','store_epoch')) or
            ready['accepted_state_version']>request['expected_state_version']):
        raise Conflict('Working plan original bootstrap source differs')
    if current and (lookup(WORKSPACE[1],workspace_head_key(original['request']))!=wh or
            lookup(BUDGET[2],wh['reservation_id'])!=context['budget_reservation'] or
            lookup(CONTROLLER[1],scope_key(request['project_id'],request['data_mode']))!=controller_head(control)):
        raise Conflict('Working plan current original heads changed')
    return intent


def validate_links(section,value,lookup,*,current=False):
    installation=_context_links(value,lookup,current=current)
    if section==SECTIONS[1]:
        request=value['request'];intent=lookup(SECTIONS[0],request['intent_key'])
        if intent is None:raise Conflict('Working plan READY original intent missing')
        validate_record(SECTIONS[0],request['intent_key'],intent)
        if (request['intent_hash']!=digest(intent) or request['intent_key']!=intent_key(request) or
                intent['accepted_state_version']>request['expected_state_version'] or
                any(request[n]!=intent['request'][n] for n in ('project_id','data_mode','store_epoch','goal_ref','plan_id')) or
                value['plan_hash']!=digest(intent['plan']) or value['expected_seal_hash']!=digest(intent['expected_seal']) or
                value['material_binding']!=intent['material_binding'] or
                stable_context(value['source_context'])!=stable_context(intent['source_context']) or
                timestamp(value['recorded_at'])<timestamp(intent['recorded_at']) or
                value['controller_checked_monotonic_ns']<intent['controller_checked_monotonic_ns']):
            raise Conflict('Working plan READY original seal/context differs')
        validate_links(SECTIONS[0],intent,lookup)
        return
    plan=value['plan'];context=value['source_context'];prep=lookup(PREPARATION[0],context['preparation']['intent_key'])
    # The two as-of fields may advance, never originate in a future or before
    # the immutable facts the actual material seed claimed to have observed.
    seed_sources=plan['sources']['sources']
    _context_links({**value,'source_context':plan['sources'],
        'request':{**value['request'],'expected_state_version':seed_sources['source_version']},
        'recorded_at':seed_sources['evaluated_at']},lookup)
    proposal=lookup(GOALS[0],context['sources']['contract_key'])['contract']['proposal']
    old=prep['plan'];candidate=_path(plan['candidate']);namespace=_path(installation['binding']['working_namespace'])
    parent=_path(value['material_binding']['published_path']).parent
    bootstrap=_path(installation['binding']['release_path']).parent
    if (candidate.parent!=namespace or
            context['observation']['kernel']['parent_identity']!=installation['binding']['working_namespace_chain'][-1] or
            parent.parent!=bootstrap or re.fullmatch(r'working_plans_[0-9a-f]{32}',parent.name) is None or
            value['expected_seal']['parent_chain'][:-1]!=installation['binding']['release_parent_chain']):
        raise Conflict('Working plan candidate/material namespace or original parent chain differs')
    expected_packet={**old['packet'],'candidate_snapshot_hash':plan['working_tree']['tree_hash']}
    if (plan['packet']!=expected_packet or any(plan[n]!=old[n] for n in ('profile','role_definition','result_schema','gates')) or
            plan['allowed_tools']!=proposal['allowed_tools'] or
            plan['allowed_command_templates']!=proposal['scope']['allowed_command_templates']):
        raise Conflict('Working plan original role/profile/schema/permissions differ')
    def name(value):
        value=value[:-1] if value.endswith('/') else value;relative_name(value);return value
    writes=[name(v) for v in proposal['scope']['writable_paths']] if plan['packet']['role']=='Engineer' else []
    protected=[name(v) for v in proposal['scope']['protected_paths']]
    available={row['name'] for row in plan['working_tree']['files']}|set(plan['working_tree']['directories'])
    if (len(writes)!=len(set(writes)) or plan['write_roots']!=[str(candidate/v) for v in writes] or
            any(v not in available or any(v==p or v.startswith(p+'/') or p.startswith(v+'/') for p in protected) for v in writes)):
        raise Conflict('Working plan approved actual write mapping differs')


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
            type(payload['format']) is not int or payload['format']!=2 or type(payload['put']) is not list or
            payload['delete']!=[] or payload['details'] is not None or event_type not in EVENTS):
        raise Conflict('closed immutable Working plan append required')
    section=SECTIONS[EVENTS.index(event_type)];rows={};markers=[]
    for row in payload['put']:
        if type(row) is not list or len(row)!=3 or row[0]!=section or type(row[1]) is not str:
            raise Conflict('Working plan extra object descriptor')
        if row[1]:
            if row[1] in rows:raise Conflict('Working plan duplicate descriptor')
            rows[row[1]]=row[2]
        else:markers.append(row[2])
    if set(rows)!={key} or markers!=([{}] if lookup(section,'') is None else []):
        raise Conflict('Working plan exact original fact/first marker required')
    value=rows[key];validate_record(section,key,value);request=value['request']
    if (lookup(section,key) is not None or object_id!=request['plan_id'] or producer!='hybrid-core' or
            version!=value['accepted_state_version'] or registration!=(request['project_id'],request['data_mode'])):
        raise Conflict('Working plan original event differs')
    validate_links(section,value,lookup,current=True)


def validate_persisted(state):
    for section in SECTIONS:
        for key,value in state.get(section,{}).items():validate_record(section,key,value)


def validate_complete(state,registration=None,event_lookup=None,*,event_summary):
    validate_persisted(state);lookup=lambda s,k:state.get(s,{}).get(k)
    ordered=sorted([(s,k,v) for s in SECTIONS for k,v in state.get(s,{}).items()],key=lambda row:row[2]['accepted_state_version'])
    for section,key,value in ordered:
        validate_links(section,value,lookup)
        if (value['accepted_state_version']>state['version'] or registration!=(value['request']['project_id'],value['request']['data_mode']) or
                event_lookup is None or event_lookup(key)!=((EVENTS[SECTIONS.index(section)],'hybrid-core',value['request']['plan_id'],
                    value['accepted_state_version']),expected_objects(section,key,value),event_inputs(value))):
            raise Conflict('Working plan original source/history differs')
    tip=None if not ordered else (ordered[-1][1],ordered[-1][2]['accepted_state_version'])
    if event_summary!=(tip,len(ordered)):raise Conflict('Working plan original historical tip/count differs')
