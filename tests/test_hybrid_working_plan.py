"""Pure-domain checks using actual original unpublished material/source facts.

The new INTENT/READY DTOs here are NOT durably written or runtime authority.
"""
from copy import deepcopy
import json

import pytest

from rlflow.hybrid_working_plan import (SECTIONS,EVENTS,intent_key,result_key,validate_record,
    validate_links,validate_transition,validate_complete,event_inputs,expected_objects)
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict
from tests.test_hybrid_working_plan_service import plans
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def facts(plans):
    owner,token,observation,_,_,_,mono=plans
    bundle=owner.prepare_plan(token,observation,'pure-original')
    entry=owner.builder._slot(bundle);plan=json.loads(entry['plan'].raw);raw=json.loads(bundle.raw)
    context=deepcopy(plan['sources']);state=owner.store.audit()
    request={'project_id':owner.workspace.project_id,'data_mode':'fixture','store_epoch':owner.workspace.store_epoch,
        'goal_ref':context['sources']['goal_ref'],'plan_id':bundle.id,'idempotency_key':'pure-intent',
        'expected_state_version':state['version'],'action':'prepare_working_plan'}
    binding={'stage_path':str(bundle.stage_path),'published_path':str(bundle.path)}
    intent={'request':request,'request_hash':digest(request),'accepted_state_version':state['version']+1,
        'source_context':context,'recorded_at':context['sources']['evaluated_at'],
        'controller_checked_monotonic_ns':mono[0],'plan':plan,'expected_seal':raw['seal'],
        'material_binding':binding,'state':'WORKING_PLAN_INTENT','execution_enabled':False,'release_enabled':False}
    ready_request={**request,'action':'publish_working_plan','expected_state_version':intent['accepted_state_version'],
        'idempotency_key':'pure-ready','intent_key':intent_key(request),'intent_hash':digest(intent)}
    ready_context=deepcopy(context);ready_context['sources']['source_version']=intent['accepted_state_version']
    ready={'request':ready_request,'request_hash':digest(ready_request),'accepted_state_version':intent['accepted_state_version']+1,
        'source_context':ready_context,'recorded_at':intent['recorded_at'],'controller_checked_monotonic_ns':mono[0],
        'plan_hash':digest(plan),'expected_seal_hash':digest(raw['seal']),'material_binding':binding,
        'state':'PLAN_READY_NONEXECUTING','execution_enabled':False,'release_enabled':False}
    return owner,bundle,state,intent,ready


def lookup(state):return lambda section,key:({} if section in state else None) if not key else state.get(section,{}).get(key)


def record(state,section,value):
    key=intent_key(value['request']) if section==SECTIONS[0] else result_key(value['request'])
    state.setdefault(section,{})[key]=value;state['version']=value['accepted_state_version']
    return key


def test_actual_material_pure_two_phase_original_sources_no_authority(facts):
    owner,bundle,state,intent,ready=facts;before=owner.store.audit()
    for phase,value in enumerate((intent,ready)):
        section=SECTIONS[phase];key=intent_key(value['request']) if not phase else result_key(value['request'])
        validate_record(section,key,value);validate_links(section,value,lookup(state),current=True)
        payload={'format':2,'put':[[section,key,value],[section,'',{}]],'delete':[],'details':None}
        validate_transition(payload,lookup(state),event_type=EVENTS[phase],key=key,
            object_id=bundle.id,producer='hybrid-core',version=value['accepted_state_version'],registration=(intent['request']['project_id'],'fixture'))
        record(state,section,value)
    sources={key:((EVENTS[phase],'hybrid-core',bundle.id,value['accepted_state_version']),
        expected_objects(SECTIONS[phase],key,value),event_inputs(value))
        for phase,section in enumerate(SECTIONS) for key,value in state[section].items()}
    tip=(result_key(ready['request']),ready['accepted_state_version'])
    validate_complete(state,(intent['request']['project_id'],'fixture'),sources.get,event_summary=(tip,2))
    assert owner.store.audit()==before and bundle.stage_path.exists() and not bundle.path.exists()
    assert event_inputs(intent)['working_plan_fact_hash']==digest(intent)
    with pytest.raises(PermissionError):owner.start(ready)


@pytest.mark.parametrize('field',['request_hash','accepted_state_version','recorded_at','controller_checked_monotonic_ns',
    'tree_hash','total_bytes','file_name','file_mode','write_roots','packet_hash','profile','schema','material_path','manifest_hash',
    'plan_file_hash','candidate','bootstrap','workspace','budget','controller','permission',
    'future_seed_version','earlier_seed_version','future_seed_time','earlier_seed_time',
    'candidate_deeper','foreign_control','parent_chain','nul_name','byte_name','deep_name','path_bytes'])
def test_rehashed_invalid_intent_rejects_original_binding(facts,field):
    _,_,state,intent,_=facts;value=deepcopy(intent)
    if field=='request_hash':value[field]='sha256:'+'0'*64
    elif field=='accepted_state_version':value[field]+=1
    elif field=='recorded_at':value[field]='2026-10-09T00:00:31Z'
    elif field=='controller_checked_monotonic_ns':value[field]=value['source_context']['observation_expires_monotonic_ns']
    elif field in ('tree_hash','total_bytes','file_name','file_mode'):
        tree=value['plan']['working_tree']
        if field=='tree_hash':tree['tree_hash']='sha256:'+'0'*64
        elif field=='total_bytes':tree['total_bytes']+=1
        elif field=='file_name':tree['files'][0]['name']='../escape'
        else:tree['files'][0]['mode']=0o644
    elif field=='write_roots':value['plan'][field]=[value['plan']['candidate']]
    elif field=='packet_hash':value['plan']['packet']['candidate_snapshot_hash']='sha256:'+'0'*64
    elif field=='profile':value['plan']['profile']['model']='different_model'
    elif field=='schema':value['plan']['result_schema']={'type':'null'}
    elif field=='material_path':value['material_binding']['published_path']+='_other'
    elif field=='manifest_hash':value['expected_seal']['manifest_hash']='sha256:'+'0'*64
    elif field=='plan_file_hash':value['expected_seal']['manifest']['files']['plan.json']='sha256:'+'0'*64
    elif field=='candidate':value['plan'][field]='/tmp/foreign-working'
    elif field=='permission':value['plan']['allowed_tools']=[]
    elif field=='candidate_deeper':value['plan']['candidate']+='/deeper'
    elif field=='foreign_control':
        from pathlib import Path
        binding=value['material_binding'];path=Path(binding['published_path'])
        binding['published_path']=str(path.parent.with_name('foreign_control')/path.name)
        binding['stage_path']=str(path.parent.with_name('foreign_control')/('.preparing-'+path.name))
    elif field=='parent_chain':value['expected_seal']['parent_chain'][0][1]+=1
    elif field in ('nul_name','byte_name','deep_name'):
        tree=value['plan']['working_tree']
        tree['files'][0]['name']=('module/bad\x00name' if field=='nul_name' else
            '/'.join(['a'*200]*21) if field=='byte_name' else '/'.join(['a']*66))
        from pathlib import Path
        tree['directories']=sorted({'.',*(str(p) for p in Path(tree['files'][0]['name']).parents if str(p)!='.')})
        tree['tree_hash']=digest({k:v for k,v in tree.items() if k not in ('tree_hash','execution_enabled')})
        value['plan']['packet']['candidate_snapshot_hash']=tree['tree_hash']
    elif field=='path_bytes':value['plan']['candidate']='/'+'界'*1400
    elif field in ('future_seed_version','earlier_seed_version','future_seed_time','earlier_seed_time'):
        seed=value['plan']['sources']['sources']
        if field=='future_seed_version':seed['source_version']+=1
        elif field=='earlier_seed_version':seed['source_version']=0
        elif field=='future_seed_time':seed['evaluated_at']='2026-10-09T00:00:01Z'
        else:seed['evaluated_at']='2026-10-08T23:59:59Z'
    else:
        context=value['source_context']
        if field=='bootstrap':context['bootstrap']['publication_hash']='sha256:'+'0'*64
        elif field=='workspace':context['workspace_claim']['origin_fact_hash']='sha256:'+'0'*64
        elif field=='budget':context['budget_reservation']['last_entry_hash']='sha256:'+'0'*64
        else:context['controller']['fact_hash']='sha256:'+'0'*64
        value['plan']['sources']=deepcopy(context)
    # Rehash deterministic plan bytes/seal so link checks, not stale hashes,
    # must reject forged permissions/profile/context/namespace.
    if field not in ('manifest_hash','plan_file_hash'):
        plan=value['plan'];seal=value['expected_seal']
        from rlflow.store import canonical
        for name,part in (('plan.json',plan),('packet.json',plan['packet']),('result.schema.json',plan['result_schema'])):
            seal['manifest']['files'][name]=digest(part);seal['file_lengths'][name]=len(canonical(part))
        seal['manifest']['plan_hash']=digest(plan);seal['manifest_hash']=digest(seal['manifest'])
    with pytest.raises((Conflict,ValueError)):
        validate_record(SECTIONS[0],intent_key(value['request']),value)
        validate_links(SECTIONS[0],value,lookup(state),current=True)


@pytest.mark.parametrize('damage',['orphan','hash','context','seal','version','scope','binding','current_head','mono_backwards'])
def test_ready_requires_original_immutable_intent_and_current_heads(facts,damage):
    _,_,state,intent,ready=facts;record(state,SECTIONS[0],intent);value=deepcopy(ready)
    if damage=='orphan':state.pop(SECTIONS[0])
    elif damage=='hash':value['request']['intent_hash']='sha256:'+'0'*64
    elif damage=='context':value['source_context']['observation']['epoch']+=1
    elif damage=='seal':value['expected_seal_hash']='sha256:'+'0'*64
    elif damage=='version':value['source_context']['sources']['source_version']-=1
    elif damage=='scope':value['request']['store_epoch']='foreign_epoch'
    elif damage=='binding':value['material_binding']['published_path']+='_other'
    elif damage=='mono_backwards':value['controller_checked_monotonic_ns']-=1
    else:
        from rlflow.hybrid_workspace import SECTIONS as WORKSPACE
        state[WORKSPACE[1]]={}
    value['request_hash']=digest(value['request'])
    with pytest.raises((Conflict,ValueError)):
        validate_record(SECTIONS[1],result_key(value['request']),value)
        validate_links(SECTIONS[1],value,lookup(state),current=True)


@pytest.mark.parametrize('damage',['missing_all','missing_intent','missing_ready','tip','count','source','registration'])
def test_complete_uses_actual_summary_even_for_empty_maps(facts,damage):
    _,bundle,state,intent,ready=facts
    record(state,SECTIONS[0],intent);record(state,SECTIONS[1],ready)
    sources={key:((EVENTS[phase],'hybrid-core',bundle.id,value['accepted_state_version']),
        expected_objects(section,key,value),event_inputs(value))
        for phase,section in enumerate(SECTIONS) for key,value in state[section].items()}
    tip=(result_key(ready['request']),ready['accepted_state_version']);summary=(tip,2)
    registration=(intent['request']['project_id'],'fixture')
    if damage=='missing_all':
        for section in SECTIONS:state.pop(section)
    elif damage=='missing_intent':state.pop(SECTIONS[0])
    elif damage=='missing_ready':state.pop(SECTIONS[1])
    elif damage=='tip':summary=((intent_key(intent['request']),intent['accepted_state_version']),2)
    elif damage=='count':summary=(tip,1)
    elif damage=='source':sources.pop(intent_key(intent['request']))
    else:registration=('foreign_project','fixture')
    with pytest.raises(Conflict):validate_complete(state,registration,sources.get,event_summary=summary)
