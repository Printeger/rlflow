"""Original accepted task -> normally retired native owner -> next approved task.

No launch consent, credentials, provider calls or synthetic completion here.
"""
import json
import threading

from .hybrid_a_condition_acceptance import fact_key,SECTION
from .hybrid_a_workflow_continuation import from_acceptance
from .hybrid_a_workflow_accounting import check_window
from .hybrid_budget import account_key,zero
from .hybrid_budget_ledger import SECTIONS as BUDGET,entry_key,scope,derived_heads,reservation_key
from .hybrid_goals import digest
from .hybrid_reads import ReadBudget
from .hybrid_preparation import source_binding,intent_key
from .store import Conflict,canonical,PREPARATION_READ_BYTES,sha


def prove_historical_links(proof,value):
    """Only the original continuation writer may reuse one immutable closure.

    Ordinary/replay/foreign lookups get the full validator. Current heads,
    Controller, physical material and deadlines are deliberately outside this.
    """
    from .hybrid_a_condition_acceptance import validate_links,original_event
    from .hybrid_fixture_runtime_ledger import _ConditionLookupProof,_CONDITION_LOOKUP_FACTORY
    from .hybrid_native_model_runtime import NativeModelOwner
    lookup=proof.lookup
    if type(proof) is not _ConditionLookupProof or getattr(lookup,'_condition_proof',None) is not proof:
        raise PermissionError('original condition lookup factory required')
    if proof._factory is not _CONDITION_LOOKUP_FACTORY:return validate_links(value,lookup)
    budget=getattr(proof.store,'_hybrid_budget_service',None)
    owner=None if budget is None else budget._fixture_runtime
    context=None if type(owner) is not NativeModelOwner else owner._continuation_parent
    active=None if context is None else owner.controller._token_active
    thread=threading.get_ident()
    if (context is None or active is None or active[0] is not proof.db or active[2] is not proof.read or
            active[3]!=thread or proof.thread!=thread or proof.read.db is not proof.db or not proof.db.in_transaction):
        return validate_links(value,lookup)
    owner._actual();prior,cap,row,root=context
    retirement=prior._continuation_retirements.get(id(cap))
    if (row['child'] is not owner or prior._continuation_roots.get(id(cap)) is not root or
            retirement is None or retirement[0] is not root or retirement[1] is not prior.sources or
            root[3:6]!=(cap.raw,row['material'],row['parent']) or prior._live or prior.sources._live or
            json.loads(root[4])['acceptance']!=value):
        raise PermissionError('original continuation retirement condition proof required')
    # This callback is reachable only from a genuine factory held by this
    # read/owned writer. Retain its full context rather than trust an attribute
    # claiming that some unrelated lookup has already validated the fact.
    contexts=getattr(proof.read,'_a_condition_lookup_contexts',None)
    if contexts is None:contexts={};proof.read._a_condition_lookup_contexts=contexts
    identity=(proof,proof.store,proof.db,proof.read,proof.state,lookup,thread)
    old=contexts.get(id(proof))
    if old is None:
        if len(contexts)>=64:raise Conflict('finite original condition proof contexts exceeded')
        contexts[id(proof)]=identity
    elif any(a is not b for a,b in zip(old[:6],identity[:6])) or old[6]!=thread:
        raise PermissionError('original condition lookup context changed')
    raw=canonical(value);cache=getattr(proof.read,'_a_continuation_condition_links',None)
    first=None if type(cache) is not tuple or len(cache)!=6 else cache[4]
    first_context=None if type(first) is not _ConditionLookupProof else contexts.get(id(first))
    completion=None if first is None else getattr(first,'_completed',None)
    if (first_context is not None and type(completion) is tuple and len(completion)==5 and
            first._factory is _CONDITION_LOOKUP_FACTORY and
            getattr(first.lookup,'_condition_proof',None) is first and
            first_context[0] is first and first_context[1] is proof.store and
            first_context[2] is proof.db and first_context[3] is proof.read and
            first_context[4] is first.state and first_context[5] is first.lookup and
            first_context[6]==thread and first.thread==thread and
            cache[0] is owner and cache[1] is root and cache[2] is retirement and cache[3]==raw and
            cache[5] is completion and completion[0] is first_context and
            completion[1] is owner and completion[2] is root and completion[3] is retirement and
            completion[4]==raw):
        # New phase dependency maps must still expose these exact original
        # immutable parents; no stale current-head cache is consulted here.
        for ref in value['parents'].values():
            parent=lookup(BUDGET[0],ref['key'])
            if parent is None or digest(parent)!=ref['hash']:raise Conflict('original cached condition parent changed')
        return
    if original_event(proof.store,proof.db,fact_key(value['request']),proof.read)!=value:
        raise Conflict('original condition proof event changed')
    validate_links(value,lookup)
    # Registration alone is not authentication: retain this exact ACK only
    # after BOTH original-event identity and the complete closure succeeded.
    completion=(contexts[id(proof)],owner,root,retirement,raw)
    proof._completed=completion
    proof.read._a_continuation_condition_links=(owner,root,retirement,raw,proof,completion)


def service(owner):
    from .hybrid_a_condition_service import ConditionAcceptanceService
    value=owner.store._hybrid_a_condition_service
    if value is None:value=ConditionAcceptanceService(owner.budget)
    if value._runtime() is not owner:raise PermissionError('original continuation condition service required')
    return value


def current(owner,lease,token,db,read,accepted,loaded,*,cleanup_root=None):
    """Current authorization is separate from the historical acceptance Controller."""
    owner._actual();attempt=owner._issued(lease);owner._unit_check(attempt)
    if cleanup_root is not None:
        row=cleanup_root[0];cap=cleanup_root[2]
        if (owner._continuation_roots.get(id(cap)) is not cleanup_root or
                owner._continuation_handoffs.get(id(cap)) is not row or cleanup_root[1] is not lease or
                cleanup_root[6] is not owner or row['cap'] is not cap or row['lease'] is not lease or
                cleanup_root[3:6]!=(cap.raw,row['material'],row['parent'])):
            raise PermissionError('original retained continuation cleanup root required')
    elif owner._safety_freeze or attempt.get('physical_safety_freeze'):
        raise Conflict('continuation frozen for cleanup')
    owner.controller.check_token_in_transaction(db,token,read)
    binding=source_binding(loaded)
    if any(binding[k]!=v for k,v in accepted['sources'].items() if k not in ('source_version','evaluated_at')):
        raise Conflict('continuation current approval differs')
    parent=attempt['entries']['FIXTURE_SCOPE_STOPPED']
    if accepted['parents']['reviewer']!={'key':entry_key(parent['request']),'hash':digest(parent)}:
        raise Conflict('continuation original Reviewer differs')
    probe={**scope(parent['request']),'action':'MARK_UNKNOWN','reservation_id':parent['request']['reservation_id']}
    head,_,_=owner.budget._heads(db,probe,read,owner.budget._metadata(db))
    if digest(head)!=accepted['budget_head_sha256']:
        raise Conflict('continuation requires untouched settled Reviewer budget head')
    now,_=owner.controller._sample()
    check_window(head['workflow'],attempt['origin']['native_model']['workflow'],now)
    return head


def prepare_input(owner,lease,token):
    from .hybrid_native_model_runtime import NativeContinuationInput
    owner._actual();owner.controller._refuse_nested_writer();owner.controller._issued(token)
    condition=service(owner)
    with owner._workflow_cpu_admission_lock,owner.pool._lock,condition._lock:
        _,attempt,reviewer=condition._review(lease)
        key=fact_key({**scope(reviewer['request']),'store_epoch':reviewer['request']['store_epoch'],
            'reviewer_terminal_key':entry_key(reviewer['request'])})
        captured={}
        def final():
            db,read=captured['context'];condition._review(lease)
            if condition._point(db,key,read)!=captured['acceptance']:
                raise Conflict('original continuation acceptance changed')
            loaded=owner.budget._load(db,reviewer['request']['goal_ref'],read)
            current(owner,lease,token,db,read,captured['acceptance'],loaded)
        def deadline(now,mono):
            from .hybrid_authority import timestamp
            if (owner._safety_freeze or attempt.get('physical_safety_freeze') or
                    now>=timestamp(captured['acceptance']['sources']['expires_at'])):
                raise Conflict('continuation expired or stopped before consumption')
            check_window(captured['head']['workflow'],attempt['origin']['native_model']['workflow'],now)
            owner._unit_effect_check(attempt)
        with owner.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                _commit_context=owner._held if owner._control_service is not None else None,
                _before_commit=final,_after_final_sample=deadline) as (db,read,_):
            accepted=condition._point(db,key,read)
            loaded=owner.budget._load(db,reviewer['request']['goal_ref'],read)
            head=current(owner,lease,token,db,read,accepted,loaded)
            parents={name:condition._lookup(db,read,BUDGET[0],ref['key']) for name,ref in accepted['parents'].items()}
            value=from_acceptance(loaded['record']['contract']['proposal'],json.loads(owner.plans.registry._raw),accepted,parents)
            raw=canonical({'acceptance':accepted,'material':value})
            captured.update(context=(db,read),acceptance=accepted,head=head)
        old=owner._continuation_inputs.get(id(lease))
        if old is not None:
            if old[0] is not lease or old[2]!=raw or old[3] is not attempt or old[1].raw!=raw:
                raise Conflict('original continuation input binding changed')
            return old[1]
        cap=NativeContinuationInput(raw)
        owner._continuation_inputs[id(lease)]=(lease,cap,raw,attempt)
        return cap


def issued_input(owner,lease,cap,token):
    from .hybrid_native_model_runtime import NativeContinuationInput
    old=owner._continuation_inputs.get(id(lease))
    if type(cap) is not NativeContinuationInput or old is None or old[0] is not lease or old[1] is not cap or cap.raw!=old[2]:
        raise PermissionError('original same-Reviewer continuation input required')
    if prepare_input(owner,lease,token) is not cap:raise Conflict('continuation input changed')
    return json.loads(cap.raw)


def cleanup_material(owner,lease,cap,token):
    """Continue ONLY an already retained original close; never reissue input."""
    root=owner._continuation_roots.get(id(cap))
    if root is None:raise PermissionError('original continuation cleanup root missing')
    condition=service(owner);_,_,reviewer=condition._review(lease)
    frozen=json.loads(root[4]);accepted=frozen['acceptance']
    with owner.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES) as (db,read,_):
        if condition._point(db,fact_key(accepted['request']),read)!=accepted:
            raise Conflict('original cleanup acceptance changed')
        loaded=owner.budget._load(db,reviewer['request']['goal_ref'],read)
        current(owner,lease,token,db,read,accepted,loaded,cleanup_root=root)
        parents={name:condition._lookup(db,read,BUDGET[0],ref['key']) for name,ref in accepted['parents'].items()}
        value=from_acceptance(loaded['record']['contract']['proposal'],json.loads(owner.plans.registry._raw),accepted,parents)
        if value!=frozen['material']:raise Conflict('original cleanup material changed')
    return frozen


def constructor_parent(context,pool,membership,plans):
    from .hybrid_native_model_runtime import NativeModelOwner,NativeContinuationInput
    from .hybrid_fixture_runtime import _owners
    if type(context) is not tuple or len(context)!=2:raise PermissionError('original continuation handoff required')
    prior,cap=context
    if type(prior) is not NativeModelOwner or type(cap) is not NativeContinuationInput:
        raise PermissionError('original native continuation parent required')
    row=prior._continuation_handoffs.get(id(cap));root=prior._continuation_roots.get(id(cap))
    retirement=prior._continuation_retirements.get(id(cap))
    if (row is None or root is None or root[0] is not row or root[2] is not cap or root[6] is not prior or
            root[3:6]!=(cap.raw,row['material'],row['parent']) or row['raw']!=cap.raw or row['cap'] is not cap or
            retirement is None or retirement[0] is not root or retirement[1] is not prior.sources or
            not row['closes'] or any(p['receipt'] is None for p in row['closes'].values()) or
            retirement[2]!=canonical({json.loads(p['observation'].raw)['workspace_id']:digest(json.loads(p['receipt']))
                for p in row['closes'].values()}) or not row['retired'] or row['child'] is not None or
            prior._live or prior.sources._live or id(prior) in _owners or prior.pool is not pool or
            prior.membership is not membership or prior.plans is not plans or plans.workspace.budget._fixture_runtime is not prior):
        raise PermissionError('original normal native retirement required for continuation')
    return prior,cap,row,root


def material(owner,loaded):
    context=owner._continuation_parent
    if context is None:raise PermissionError('original accepted native continuation handoff required')
    prior,cap,row,root=context;retirement=prior._continuation_retirements.get(id(cap))
    if (row['child'] is not owner or prior._continuation_roots.get(id(cap)) is not root or
            root[0] is not row or root[2] is not cap or root[6] is not prior or
            root[3:6]!=(cap.raw,row['material'],row['parent']) or
            retirement is None or retirement[0] is not root or retirement[1] is not prior.sources or prior._live or prior.sources._live):
        raise PermissionError('original normally retired continuation root required')
    frozen=json.loads(root[4]);accepted=frozen['acceptance']
    if any(accepted['sources'][k]!=loaded[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')):
        raise Conflict('continuation current approval changed')
    def prove(db,read):
        cache=getattr(read,'_a_continuation_parent_proof',None)
        if cache is not None and cache[0] is root and cache[1] is retirement and cache[2]==root[4]:return cache[3]
        from .hybrid_fixture_runtime_ledger import dependency_lookup
        from .hybrid_preparation_sources import historical_sources
        # Use the SAME authenticated historical closure as the ledger. The
        # service _point would independently expand all three Budget parents
        # and then repeat their complete links again in this owned writer.
        lookup=dependency_lookup(owner.store,db,read,historical_sources(owner.store,db,accepted['sources'],read))
        if lookup(SECTION,fact_key(accepted['request']))!=accepted:
            raise Conflict('original continuation acceptance event changed')
        lookup._condition_proof(accepted)
        parents={name:lookup(BUDGET[0],ref['key']) for name,ref in accepted['parents'].items()}
        read._a_continuation_parent_proof=(root,retirement,root[4],parents)
        return parents
    active=owner.controller._token_active
    if active is not None:
        if active[3]!=threading.get_ident() or not active[0].in_transaction:raise PermissionError('original continuation writer required')
        parents=prove(active[0],active[2])
    else:
        with owner.store.read_connection() as db:
            db.execute('BEGIN');parents=prove(db,ReadBudget(db,PREPARATION_READ_BYTES))
    value=from_acceptance(loaded['record']['contract']['proposal'],json.loads(owner.plans.registry._raw),accepted,parents)
    if value!=frozen['material']:raise Conflict('original continuation task material changed')
    return value,accepted,parents


def admission(owner,loaded,*,reserved=False):
    value,accepted,parents=material(owner,loaded);reviewer=parents['reviewer']
    probe={**scope(reviewer['request']),'action':'MARK_UNKNOWN','reservation_id':reviewer['request']['reservation_id']}
    with owner.store.read_connection() as db:
        db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
        head,_,_=owner.budget._heads(db,probe,read,owner.budget._metadata(db))
        if not reserved:
            if digest(head)!=accepted['budget_head_sha256']:raise Conflict('original settled continuation head changed')
        else:
            sequence=owner._continuation_plan_sequence
            if sequence is None or 'reserved' not in sequence:raise Conflict('original continuation reservation required')
            reserve=sequence['reserved']
            if owner.budget._point(db,entry_key(reserve['request']),read)!=reserve:
                raise Conflict('original continuation reserve event changed')
            owner.budget._dependencies(db,reserve,read)
            expected=derived_heads(reserve)[BUDGET[1]][account_key(scope(probe))]
            if head!=expected or digest(reserve['prior_goal'])!=accepted['budget_head_sha256']:
                raise Conflict('exact original continuation reservation head required')
    workflow=reviewer['request']['fixture_runtime']['origin']['native_model']['workflow']
    now,_=owner.controller._sample();check_window(head['workflow'],workflow,now)
    charge=value['spec']['seconds']+10
    if ('continuation_entry' in head['workflow'] or
            head['workflow']['medium_sessions']+1>workflow['limits']['medium_sessions'] or
            head['workflow']['controlled_seconds_charged']+charge>workflow['limits']['controlled_seconds']):
        raise Conflict('original unique continuation quota exhausted')
    return value,accepted,parents


def prepare_plan(owner,token):
    owner._actual();owner.controller._issued(token);owner.controller.check_token(token)
    if not owner._workflow_cpu_sequence_lock.acquire(blocking=False):raise Conflict('continuation preparation active')
    try:
        if owner._continuation_plan_sequence is not None:raise Conflict('continuation preparation attempted; no remint')
        if owner._continuation_parent is None:raise PermissionError('original continuation parent required')
        accepted=json.loads(owner._continuation_parent[3][4])['acceptance']
        with owner.store.read_connection() as db:
            db.execute('BEGIN');loaded=owner.budget._load(db,accepted['request']['goal_ref'],ReadBudget(db,PREPARATION_READ_BYTES))
        value,accepted,_=admission(owner,loaded);spec=value['spec']
        key='a_continue_'+sha(value['acceptance'])
        scope_value={**scope(accepted['request']),'store_epoch':accepted['request']['store_epoch']}
        sequence={'token':token,'phase':'PREPARATION','observation':None,'bundle':None}
        owner._continuation_plan_sequence=sequence
        def step(phase,call,field=None):
            with owner._workflow_cpu_admission_lock:
                owner._actual()
                if owner._safety_freeze:raise Conflict('continuation preparation frozen')
                sequence['phase']=phase;result=call()
                if field is not None:sequence[field]=result
                return result
        request={'idempotency_key':key+'_prepare','project_id':scope_value['project_id'],
            'data_mode':scope_value['data_mode'],'goal_ref':scope_value['goal_ref'],'role':'Engineer',
            'context':{'text':'Continue the explicitly approved next task using the accepted candidate in frozen model input. '
                'WorkingCopy remains the original source baseline, not this accepted candidate. Task: '+value['packet']['objective']}}
        step('PREPARATION',lambda:owner.workspace.preparation.prepare(request));intent=intent_key(request)
        reserve={**scope_value,'idempotency_key':key+'_reserve','expected_state_version':owner.store.version(),
            'action':'RESERVE','preparation_intent_key':intent,'purpose':'EXECUTION',
            'amount':{**zero(),'model_sessions':1,'model_input_tokens':spec['model_input_tokens'],
                'model_output_tokens':spec['model_output_tokens'],'wall_seconds':spec['seconds']+10}}
        sequence['reserve']=reserve
        step('RESERVE',lambda:owner.budget.record(reserve,token)['entry'],'reserved')
        observation=step('STAGE',lambda:owner.workspace.stage(intent,ttl_seconds=60),'observation')
        acquire={**scope_value,'idempotency_key':key+'_workspace','expected_state_version':owner.store.version(),
            'expected_workspace_revision':0,'workspace_id':json.loads(observation.raw)['workspace_id'],
            'reservation_id':reservation_key(reserve),'operation':'acquire','ttl_seconds':60}
        step('ACQUIRE',lambda:owner.workspace.record(acquire,token,observation))
        bundle=step('PLAN',lambda:owner.plans.prepare_plan(token,observation,key+'_plan'),'bundle')
        step('INTENT',lambda:owner.plans.persist_intent(bundle,token,observation,expected_version=owner.store.version()))
        step('PUBLISH',lambda:owner.plans.publish(bundle,token,observation,expected_version=owner.store.version()))
        sequence['phase']='READY';return bundle,observation
    finally:owner._workflow_cpu_sequence_lock.release()


def grant(owner,bundle,token,observation):
    owner._actual();owner.controller._issued(token)
    sequence=owner._continuation_plan_sequence
    if sequence is None or sequence['phase']!='READY' or sequence['bundle'] is not bundle or sequence['observation'] is not observation:
        raise PermissionError('original next-task continuation plan required')
    with owner.store.read_connection() as db:
        db.execute('BEGIN');loaded=owner.budget._load(db,owner._ready_for_bundle(bundle)['request']['goal_ref'],ReadBudget(db,PREPARATION_READ_BYTES))
    value,_,_=admission(owner,loaded,reserved=True)
    intent,_=owner._plan_original(bundle,token,observation)
    source=intent['source_context']
    reserve=sequence['reserve']
    if (source['budget_reservation']['reservation_id']!=reservation_key(reserve) or
            source['preparation']['intent_key']!=reserve['preparation_intent_key']):
        raise Conflict('original continuation reservation and plan lineage differ')
    return owner.issue_native_model_grant(bundle,token,observation,packet=value['packet'],output_schema=value['schema'],_workflow='continuation')
