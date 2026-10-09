"""Closed budget ledger domain under construction; no service or release API.

Arithmetic/derived objects alone are not original-source proofs. Store and
protected-owner integration must validate those separately before any write.
"""
from .hybrid_protocol import ID,HASH,TIME,obj,enum,validate_schema
from .hybrid_goals import digest,check_bytes,SECTIONS as GOALS
from .hybrid_preparation import (SOURCES,SECTIONS as PREPARATION,_references,_intent_links,_result_links,
    validate_record as preparation_record)
from .hybrid_controller import (SECTIONS as CONTROLLER,validate_record as controller_record,
    fact_key as controller_key,scope_key as controller_scope,head as controller_head)
from .hybrid_authority import timestamp
from .hybrid_admission import PREPARATION_REF,CONTROLLER_REF
from .hybrid_budget import (DIMENSIONS,MAXIMUM,SCOPE,account_key,zero,vector,add,subtract,
    balances,validate_balances,finalization_floor,reserve,rebase,mark_unknown,cancel_held)
from .store import Conflict,sha

SECTIONS=('hybrid_budget_entries','hybrid_budget_goal_heads',
          'hybrid_budget_reservation_heads','hybrid_budget_project_heads')
EVENT='HYBRID_BUDGET_RECORDED'
COUNT={'type':'integer','minimum':0,'maximum':MAXIMUM}
POSITIVE={**COUNT,'minimum':1}
VECTOR=obj(dict.fromkeys(DIMENSIONS,COUNT))
BALANCES=obj(dict.fromkeys(DIMENSIONS,obj(dict.fromkeys(
    ('limit','consumed','reserved','unknown_exposure','available','overrun'),COUNT))))
POLICY=obj({**dict.fromkeys(DIMENSIONS,COUNT),'model_token_enforcement':enum('hard_required','soft_approved'),
    'finalization_reserve_fraction':{'type':'number','minimum':0,'maximum':0.8}})
COMMON={**SCOPE['properties'],'store_epoch':ID,'idempotency_key':ID,'expected_state_version':COUNT}
REQUEST={'oneOf':[
    obj({**COMMON,'action':{'const':'RESERVE'},'preparation_intent_key':ID,
         'amount':VECTOR,'purpose':{'const':'EXECUTION'}}),
    obj({**COMMON,'action':enum('MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'),'reservation_id':ID})]}
GOAL_DATA={'scope':SCOPE,'policy':POLICY,'policy_source':SOURCES,'balance':BALANCES}
RESERVATION_DATA={'scope':SCOPE,'reservation_id':ID,'origin_entry_key':ID,
    'preparation':PREPARATION_REF,'origin_sources':SOURCES,'amount':VECTOR,
    'purpose':{'const':'EXECUTION'},'status':enum('HELD','DENIED','UNKNOWN','CANCELLED'),
    'runtime_registration':{'const':'NOT_AUTHORIZED'},'execution_enabled':{'const':False}}
PROJECT_DATA={'project_id':ID,'data_mode':enum('live','fixture'),
    'consumed':VECTOR,'reserved':VECTOR,'unknown_exposure':VECTOR}
POINTER={'last_entry_key':ID,'last_entry_hash':HASH,'accepted_state_version':POSITIVE}
HEADS=(obj({**GOAL_DATA,**POINTER}),obj({**RESERVATION_DATA,**POINTER}),obj({**PROJECT_DATA,**POINTER}))
nullable=lambda schema:{'oneOf':[schema,{'type':'null'}]}
ENTRY=obj({'schema_version':{'const':'1.0'},'request':REQUEST,'request_hash':HASH,
    'policy_source':SOURCES,'policy':POLICY,'preparation':PREPARATION_REF,'controller':CONTROLLER_REF,
    'recorded_at':TIME,'controller_checked_monotonic_ns':COUNT,
    'prior_goal':nullable(HEADS[0]),'prior_reservation':nullable(HEADS[1]),'prior_project':nullable(HEADS[2]),
    'decision':enum('HELD','DENIED','UNKNOWN','CANCELLED'),
    'reason':enum('BUDGET_RESERVED','BUDGET_UNAVAILABLE','EXPOSURE_UNKNOWN','CORE_CANCELLED_BEFORE_RUNTIME'),
    'accepted_state_version':POSITIVE,'execution_enabled':{'const':False}})


def scope(request):
    return {name:request[name] for name in SCOPE['properties']}


def entry_key(request):
    # One idempotency namespace across actions; differing request is a conflict.
    return 'budget_entry_'+sha([request['project_id'],request['data_mode'],request['idempotency_key']])


def reservation_key(request):
    return 'budget_reservation_'+sha(entry_key(request))


def project_key(project_id,data_mode):
    return 'budget_project_'+sha([project_id,data_mode])


def policy_limits(policy):
    validate_schema(POLICY,policy)
    limits=vector({name:policy[name] for name in DIMENSIONS})
    finalization_floor(limits,policy['finalization_reserve_fraction'])
    if limits['wall_seconds']==0:raise Conflict('approved budget wall limit must be positive')
    return limits


def _head_base(value):
    return {name:item for name,item in value.items() if name not in POINTER}


def derived_heads(value):
    """Deterministic local transition, NOT proof that prior heads are original."""
    request=value['request'];owner=scope(request);limits=policy_limits(value['policy'])
    previous=value['prior_goal'];prior_reservation=value['prior_reservation'];prior_project=value['prior_project']
    if previous is not None and previous['scope']!=owner:raise Conflict('budget prior Goal scope differs')
    if prior_reservation is not None and prior_reservation['scope']!=owner:
        raise Conflict('budget prior reservation scope differs')
    if prior_project is not None and (prior_project['project_id'],prior_project['data_mode'])!=(owner['project_id'],owner['data_mode']):
        raise Conflict('budget prior project scope differs')
    old_balance=previous['balance'] if previous is not None else balances(limits,zero(),zero(),zero())
    old=validate_balances(old_balance)
    if request['action']=='RESERVE':
        if prior_reservation is not None:raise Conflict('new budget reservation already exists')
        amount=vector(request['amount'])
        if not any(amount.values()):raise Conflict('empty reservation refused')
        changed=rebase(old_balance,limits)
        try:
            changed=reserve(changed,amount,purpose=request['purpose'],fraction=value['policy']['finalization_reserve_fraction'])
            decision,reason='HELD','BUDGET_RESERVED'
        except Conflict:
            decision,reason='DENIED','BUDGET_UNAVAILABLE'
        reservation={'scope':owner,'reservation_id':reservation_key(request),'origin_entry_key':entry_key(request),
            'preparation':value['preparation'],'origin_sources':value['policy_source'],'amount':amount,
            'purpose':'EXECUTION','status':decision,'runtime_registration':'NOT_AUTHORIZED','execution_enabled':False}
    else:
        if (previous is None or prior_reservation is None or
                prior_reservation['reservation_id']!=request['reservation_id'] or
                prior_reservation['status']!='HELD' or prior_reservation['runtime_registration']!='NOT_AUTHORIZED'):
            raise Conflict('exact PRE_RUNTIME HELD reservation required')
        if value['policy']!=previous['policy'] or value['policy_source']!=previous['policy_source']:
            raise Conflict('cleanup cannot replace current approved budget policy')
        if value['preparation']!=prior_reservation['preparation']:
            raise Conflict('cleanup cannot replace original preparation')
        reservation=_head_base(prior_reservation)
        if request['action']=='MARK_UNKNOWN':
            changed=mark_unknown(old_balance,reservation['amount']);decision,reason='UNKNOWN','EXPOSURE_UNKNOWN'
        else:
            changed=cancel_held(old_balance,reservation['amount']);decision,reason='CANCELLED','CORE_CANCELLED_BEFORE_RUNTIME'
        reservation={**reservation,'status':decision}
    if (value['decision'],value['reason'])!=(decision,reason):raise Conflict('budget decision differs from exact arithmetic')
    goal={'scope':owner,'policy':value['policy'],'policy_source':value['policy_source'],'balance':changed}
    new=validate_balances(changed)
    project=_head_base(prior_project) if prior_project is not None else {
        'project_id':owner['project_id'],'data_mode':owner['data_mode'],
        'consumed':zero(),'reserved':zero(),'unknown_exposure':zero()}
    if previous is not None and prior_project is None:raise Conflict('budget prior project missing')
    for field in ('consumed','reserved','unknown_exposure'):
        project[field]=add(subtract(project[field],old[field]),new[field])
    if any(project['unknown_exposure'][name]>project['reserved'][name] for name in DIMENSIONS):
        raise Conflict('project unknown exceeds retained exposure')
    pointer={'last_entry_key':entry_key(request),'last_entry_hash':digest(value),
             'accepted_state_version':value['accepted_state_version']}
    return {SECTIONS[1]:{account_key(owner):{**goal,**pointer}},
        SECTIONS[2]:{reservation['reservation_id']:{**reservation,**pointer}},
        SECTIONS[3]:{project_key(owner['project_id'],owner['data_mode']):{**project,**pointer}}}


def validate_record(section,key,value):
    check_bytes(value,256*1024)
    if section==SECTIONS[0]:
        validate_schema(ENTRY,value);request=value['request']
        if key!=entry_key(request) or value['request_hash']!=digest(request):raise Conflict('budget entry identity differs')
        if (type(request['expected_state_version']) is not int or
                value['accepted_state_version']!=request['expected_state_version']+1 or
                type(value['accepted_state_version']) is not int or
                type(value['controller_checked_monotonic_ns']) is not int):
            raise Conflict('actual budget version and clock required')
        for index,name in enumerate(('prior_goal','prior_reservation','prior_project')):
            head=value[name]
            if head is not None:
                headkey=(account_key(head['scope']) if index==0 else head['reservation_id'] if index==1
                         else project_key(head['project_id'],head['data_mode']))
                validate_record(SECTIONS[index+1],headkey,head)
                if type(head['accepted_state_version']) is not int or head['accepted_state_version']>=value['accepted_state_version']:
                    raise Conflict('budget predecessor is not earlier')
        derived_heads(value)
    elif section in SECTIONS[1:]:
        index=SECTIONS[1:].index(section);validate_schema(HEADS[index],value)
        if type(value['accepted_state_version']) is not int:raise Conflict('actual budget head version required')
        if index==0:
            expected=account_key(value['scope']);limits=policy_limits(value['policy'])
            base=validate_balances(value['balance'])
            if base['limit']!=limits:raise Conflict('budget head balance limits differ from approved policy')
            if any(value['policy_source'][name]!=item for name,item in value['scope'].items()):
                raise Conflict('budget head policy source scope differs')
        elif index==1:
            expected=value['reservation_id'];vector(value['amount'])
        else:
            expected=project_key(value['project_id'],value['data_mode'])
            for field in ('consumed','reserved','unknown_exposure'):vector(value[field])
            if any(value['unknown_exposure'][name]>value['reserved'][name] for name in DIMENSIONS):
                raise Conflict('project unknown exceeds reserved')
        if key!=expected:raise Conflict('budget derived head key differs')
    else:raise Conflict('unknown budget section')


def _reservation_id(request):
    return reservation_key(request) if request['action']=='RESERVE' else request['reservation_id']


def _keys(request):
    return (account_key(scope(request)),_reservation_id(request),project_key(request['project_id'],request['data_mode']))


def expected_objects(value):
    result=[(SECTIONS[0],entry_key(value['request']),digest(value))]
    result.extend((section,key,digest(head)) for section,values in derived_heads(value).items() for key,head in values.items())
    return sorted(result)


def event_inputs(value):
    return {'budget_entry_hash':digest(value),'budget_goal_account_key':account_key(scope(value['request'])),
            'budget_reservation_id':_reservation_id(value['request'])}


def validate_links(value,lookup,*,current=False):
    """Historical original references, with new transition's exact current heads.

    Actual original-event byte proofs and live owner freshness remain Store/
    service responsibilities, not permissions supplied by this lookup function.
    """
    request=value['request'];owner=scope(request);sources=value['policy_source']
    if any(sources[name]!=item for name,item in owner.items()):raise Conflict('budget policy source scope differs')
    _references(sources,lookup,current=current and request['action']=='RESERVE')
    contract=lookup(GOALS[0],sources['contract_key'])
    if value['policy']!=contract['contract']['proposal']['budget']:raise Conflict('budget policy differs from original contract')
    if sources['source_version']>request['expected_state_version']:raise Conflict('budget policy source from future')
    keys=_keys(request)
    for section,key,name in zip(SECTIONS[1:],keys,('prior_goal','prior_reservation','prior_project')):
        prior=value[name]
        if current and lookup(section,key)!=prior:raise Conflict('budget prior projected head changed')
        if prior is None:continue
        previous=lookup(SECTIONS[0],prior['last_entry_key'])
        if previous is None:raise Conflict('budget original predecessor entry missing')
        validate_record(SECTIONS[0],prior['last_entry_key'],previous)
        if derived_heads(previous).get(section,{}).get(key)!=prior:
            raise Conflict('budget predecessor is not exact original derived head')
    ref=value['preparation'];intent=lookup(PREPARATION[0],ref['intent_key']);outcome=lookup(PREPARATION[1],ref['result_key'])
    if intent is None or outcome is None:raise Conflict('budget original preparation missing')
    preparation_record(PREPARATION[0],ref['intent_key'],intent);preparation_record(PREPARATION[1],ref['result_key'],outcome)
    _intent_links(intent,lookup);_result_links(outcome,intent,lookup)
    if (outcome['status']!='PREPARED' or ref['intent_hash']!=digest(intent) or ref['result_hash']!=digest(outcome) or
            intent['sources']['goal_ref']!=owner['goal_ref'] or
            any(intent['sources'][name]!=owner[name] for name in ('project_id','data_mode')) or
            max(intent['accepted_state_version'],outcome['accepted_state_version'])>=value['accepted_state_version']):
        raise Conflict('budget original preparation reference differs')
    if request['action']=='RESERVE':
        if (request['preparation_intent_key']!=ref['intent_key'] or sources['store_epoch']!=request['store_epoch'] or
                sources['source_version']!=request['expected_state_version'] or value['recorded_at']!=sources['evaluated_at'] or
                not timestamp(sources['evaluated_at'])<timestamp(sources['expires_at']) or
                any(sources[name]!=item for name,item in intent['sources'].items() if name not in ('source_version','evaluated_at'))):
            raise Conflict('budget reserve is not current original preparation consent')
    else:
        prior=value['prior_reservation'];original=lookup(SECTIONS[0],prior['origin_entry_key'])
        if (original is None or original['request']['action']!='RESERVE' or original['decision']!='HELD' or
                derived_heads(original)[SECTIONS[2]].get(prior['reservation_id'])!=prior):
            raise Conflict('cleanup requires exact original pre-runtime HELD head')
        if timestamp(value['recorded_at'])<timestamp(original['recorded_at']):raise Conflict('budget cleanup clock regressed')
    cr=value['controller'];control=lookup(CONTROLLER[0],cr['fact_key'])
    if control is None:raise Conflict('budget original controller missing')
    controller_record(CONTROLLER[0],cr['fact_key'],control);control_request=control['request']
    if (cr!={'fact_key':controller_key(control_request),'fact_hash':digest(control),
             'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']} or
            any(control_request[name]!=request[name] for name in ('project_id','data_mode','store_epoch')) or
            control['accepted_state_version']>=value['accepted_state_version'] or
            not timestamp(control['issued_at'])<=timestamp(value['recorded_at'])<timestamp(control['expires_at']) or
            not control['issued_monotonic_ns']<=value['controller_checked_monotonic_ns']<control['expires_monotonic_ns'] or
            (request['action']=='RESERVE' and control['config_hash']!=sources['config_hash'])):
        raise Conflict('budget original controller capture differs')
    if current and lookup(CONTROLLER[1],controller_scope(request['project_id'],request['data_mode']))!=controller_head(control):
        raise Conflict('budget controller is not current head')


def validate_transition(payload,lookup,*,event_type,key,object_id,producer,version,registration):
    if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
            type(payload['format']) is not int or payload['format']!=2 or
            type(payload['put']) is not list or type(payload['delete']) is not list or
            payload['delete'] or payload['details'] is not None):raise Conflict('closed budget append transaction required')
    rows={};markers={}
    for item in payload['put']:
        if type(item) is not list or len(item)!=3 or not all(type(v) is str for v in item[:2]):
            raise Conflict('budget descriptor invalid')
        section,objkey,value=item
        if section not in SECTIONS or (section,objkey) in rows or section in markers and not objkey:
            raise Conflict('budget extra or duplicate object')
        if not objkey:markers[section]=value
        else:rows[(section,objkey)]=value
    entries=[(k,v) for (s,k),v in rows.items() if s==SECTIONS[0]]
    if len(entries)!=1:raise Conflict('exact one immutable budget entry required')
    entry_id,value=entries[0];validate_record(SECTIONS[0],entry_id,value)
    expected={(SECTIONS[0],entry_id):value}
    expected.update({(s,k):v for s,values in derived_heads(value).items() for k,v in values.items()})
    if rows!=expected or markers!={s:{} for s in SECTIONS if lookup(s,'') is None}:
        raise Conflict('budget exact derived objects and initial markers required')
    request=value['request']
    if (lookup(SECTIONS[0],entry_id) is not None or event_type!=EVENT or key!=entry_id or
            object_id!=account_key(scope(request)) or producer!='hybrid-core' or value['accepted_state_version']!=version or
            registration!=(request['project_id'],request['data_mode'])):raise Conflict('budget original event binding differs')
    validate_links(value,lookup,current=True)


def validate_persisted(state):
    for section in SECTIONS:
        for key,value in state.get(section,{}).items():validate_record(section,key,value)


def validate_complete(state,registration=None,event_lookup=None,*,event_summary=(None,0)):
    validate_persisted(state);entries=state.get(SECTIONS[0],{});derived={s:{} for s in SECTIONS[1:]}
    lookup=lambda s,k:state.get(s,{}).get(k)
    ordered=sorted(entries.items(),key=lambda pair:pair[1]['accepted_state_version'])
    for key,value in ordered:
        request=value['request']
        if (value['accepted_state_version']>state['version'] or event_lookup is None or event_lookup(key)!=(
                (EVENT,'hybrid-core',account_key(scope(request)),value['accepted_state_version']),expected_objects(value)) or
                registration!=(request['project_id'],request['data_mode'])):raise Conflict('budget original source proof differs')
        for section,objkey,name in zip(SECTIONS[1:],_keys(request),('prior_goal','prior_reservation','prior_project')):
            if value[name]!=derived[section].get(objkey):raise Conflict('budget history does not continue exact prior head')
        validate_links(value,lookup)
        for section,values in derived_heads(value).items():derived[section].update(values)
    if any(state.get(s,{})!=values for s,values in derived.items()):raise Conflict('budget historical derived heads differ')
    latest=ordered[-1] if ordered else None
    if event_summary!=(None if latest is None else (latest[0],latest[1]['accepted_state_version']),len(entries)):
        raise Conflict('budget historical domain differs from original tip/count')
