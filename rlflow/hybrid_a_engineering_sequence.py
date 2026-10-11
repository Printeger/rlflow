"""Finite A orchestration of original APIs, not an execution consent issuer.

No provider, credential, GPU or automatic repair/retry operation lives here.
Every model launch must come from the separately authorized original issuer.
"""
import json
import os

from .store import Conflict,canonical,sha


def _creator(owner):
    from .hybrid_native_model_runtime import NativeModelOwner
    from .jobs import identity
    # The foreign PID refusal precedes all inherited Events/locks and IO.
    if type(owner) is not NativeModelOwner or os.getpid()!=owner.process['pid']:
        raise PermissionError('original A sequence creator process required')
    if identity(os.getpid())!=owner.process:
        raise PermissionError('original A sequence process identity changed')


def run(owner,lease,*,launch,launch_issuer):
    """One original Engineer -> CPU -> Reviewer -> conditions -> explicit next task.

    CPU FAIL / Reviewer REVISE are NOT_ACCEPTED, not repair authorization.
    Exceptions latch the sequence and clean the original current owner; no
    redispatch, fabricated settlement or failed-STOP success is returned.
    launch_issuer(owner, lease) must return that lease's genuine native launch;
    this entry never stages account credentials or substitutes a consent bool.
    """
    if not callable(launch_issuer):raise TypeError('explicit authorized original launch issuer required')
    _creator(owner)
    if not owner._workflow_engineering_lock.acquire(blocking=False):
        raise Conflict('original A engineering sequence already running')
    try:
        if owner._workflow_engineering_sequence is not None:
            raise Conflict('original A engineering sequence already latched; no redispatch')
        if owner._workflow_engineering_stop.is_set():raise Conflict('original A sequence permanently stopped')
        owner._actual();attempt=owner._issued(lease);owner._unit_check(attempt)
        workflow=attempt['origin']['native_model'].get('workflow',{})
        if (workflow.get('stage')!='FIRST_ENGINEER' or
                workflow.get('accounting_version')!='A_REGISTRATION_CEILINGS_V1'):
            raise PermissionError('original accounted FIRST_ENGINEER entry required')
        owner._check_launch(attempt,launch)
        owner.controller._refuse_nested_writer()
        sequence={'phase':'ENGINEER','owner':owner,'lease':lease,'launch':launch,
            'launch_issuer':launch_issuer,'token':attempt['token'],'result':None}
        owner._workflow_engineering_sequence=sequence
        budget,pool,membership=owner.budget,owner.pool,owner.membership
        owner._workflow_engineering_root=(owner,sequence,budget,pool,membership,owner._workflow_engineering_stop)
        key='a_sequence_'+sha([lease.id,workflow['envelope_sha256']])
        outputs={}

        def step(phase,operation):
            current=sequence['owner']
            with current._workflow_cpu_admission_lock:
                current._actual()
                if (owner._workflow_engineering_stop.is_set() or current._safety_freeze or budget._fixture_runtime is not current or
                        current.pool is not pool or current.membership is not membership or current.budget is not budget):
                    raise Conflict('original A sequence frozen or current owner changed')
                sequence['phase']=phase
                return operation(current)

        def renew(phase):
            # Existing Controller renewal is not an A window/quota reset.
            sequence['token']=step(phase,lambda current:current.controller.renew(sequence['token'],
                key+'_'+phase.lower(),expected_version=current.store.version(),ttl_seconds=60)['token'])

        def native_run(phase,current,task,qualified):
            step(phase,lambda current:None)
            # Never hold orchestration/admission locks over the model loop;
            # original runtime STOP and final current gates remain independent.
            return current.run_workflow_native(task,launch=qualified)

        def qualify_launch(phase,current,task):
            step(phase,lambda current:None)
            # The authorized issuer can block on account/material IO. Never
            # hold an admission lock across external code: STOP stays free.
            qualified=launch_issuer(current,task)
            step(phase+'_CHECK',lambda current:current._check_launch(current._issued(task),qualified))
            return qualified

        def finish(status,reason):
            step('FINAL_CHECK',lambda current:None)
            result={'status':status,'reason':reason,'outputs':outputs,
                'goal_completed':False,'current_activation':'NOT_RECHECKED',
                'repair_dispatched':False}
            raw=canonical(result)
            owner._workflow_engineering_completed=(sequence,raw)
            sequence['result']=raw;sequence['phase']=status
            return json.loads(raw)

        try:
            outputs['engineer']=native_run('ENGINEER',owner,lease,launch)
            renew('CPU_TOKEN')
            cap=step('CPU_INPUT',lambda current:current.prepare_workflow_cpu_input(lease))
            cpu=step('CPU_HANDOFF',lambda current:current.handoff_workflow_cpu(lease,cap,token=sequence['token']))
            sequence['owner']=cpu
            step('CPU',lambda current:None)
            outputs['cpu']=cpu.execute_workflow_cpu(sequence['token'])
            if (outputs['cpu']['machine_acceptance']['status']!='PASS' or
                    outputs['cpu'].get('execution',{}).get('status')!='SUCCEEDED'):
                return finish('NOT_ACCEPTED','CPU_CHECKS_FAILED')
            task=cpu._workflow_cpu_sequence['lease']
            renew('REVIEWER_TOKEN')
            cap=step('REVIEWER_INPUT',lambda current:current.prepare_workflow_reviewer_input(task))
            reviewer=step('REVIEWER_HANDOFF',lambda current:current.handoff_workflow_reviewer(task,cap,token=sequence['token']))
            sequence['owner']=reviewer
            renew('REVIEWER_PLAN_TOKEN')
            bundle,observation=step('REVIEWER_PLAN',lambda current:current.prepare_workflow_reviewer_plan(sequence['token']))
            grant=step('REVIEWER_GRANT',lambda current:current.issue_workflow_reviewer_grant(bundle,sequence['token'],observation))
            claim=step('REVIEWER_CLAIM',lambda current:current.pool.claim(current.membership,
                expected_version=current.pool.snapshot()['version'],request_key=key+'_reviewer_claim',seconds=60))
            task=step('REVIEWER_REGISTER',lambda current:current.register(bundle,sequence['token'],observation,claim,
                request_key=key+'_reviewer_task',scenario='native_model',native_model_grant=grant))
            qualified=qualify_launch('REVIEWER_LAUNCH',reviewer,task)
            outputs['reviewer']=native_run('REVIEWER',reviewer,task,qualified)
            if outputs['reviewer']['result']['review']['verdict']!='ACCEPT':
                return finish('NOT_ACCEPTED','REVIEWER_NOT_ACCEPTED')
            renew('CONDITION_TOKEN')
            outputs['acceptance']=step('CONDITIONS',lambda current:current.accept_workflow_conditions(task,
                sequence['token'],idempotency_key=key+'_conditions',expected_state_version=current.store.version()))
            spec=json.loads(reviewer.plans.registry._raw)['tools']['native_model']['definition']['spec']
            if 'continuation_task' not in spec:return finish('ACCEPTED','NO_EXPLICIT_CONTINUATION_DEMAND')
            renew('CONTINUATION_TOKEN')
            cap=step('CONTINUATION_INPUT',lambda current:current.prepare_workflow_continuation_input(task,sequence['token']))
            next_owner=step('CONTINUATION_HANDOFF',lambda current:current.handoff_workflow_continuation(task,cap,token=sequence['token']))
            sequence['owner']=next_owner
            renew('CONTINUATION_PLAN_TOKEN')
            bundle,observation=step('CONTINUATION_PLAN',lambda current:current.prepare_workflow_continuation_plan(sequence['token']))
            grant=step('CONTINUATION_GRANT',lambda current:current.issue_workflow_continuation_grant(bundle,sequence['token'],observation))
            claim=step('CONTINUATION_CLAIM',lambda current:current.pool.claim(current.membership,
                expected_version=current.pool.snapshot()['version'],request_key=key+'_continuation_claim',seconds=60))
            task=step('CONTINUATION_REGISTER',lambda current:current.register(bundle,sequence['token'],observation,claim,
                request_key=key+'_continuation_task',scenario='native_model',native_model_grant=grant))
            qualified=qualify_launch('CONTINUATION_LAUNCH',next_owner,task)
            outputs['continuation']=native_run('CONTINUATION',next_owner,task,qualified)
            return finish('ACCEPTED_AND_CONTINUED','ORIGINAL_CONDITION_ACCEPTANCE_AND_ONE_NEXT_RUN')
        except BaseException as primary:
            sequence['phase']='FAILED'
            # Lost handoff installation may have installed the original child
            # before its return. Only the same coordinator's current owner is
            # cleaned, never an unrelated runtime supplied by a callback.
            current=budget._fixture_runtime
            if (current is not None and current.budget is budget and current.pool is pool and
                    current.membership is membership and current._live):
                sequence['owner']=current
                try:current.shutdown()
                except BaseException as cleanup:
                    primary.add_note('Original A owner STOP incomplete: '+type(cleanup).__name__)
                    try:current.shutdown_safety()
                    except BaseException as safety:
                        primary.add_note('Original A safety cleanup incomplete: '+type(safety).__name__)
            raise
    finally:owner._workflow_engineering_lock.release()


def stop(owner):
    """Original root remains the STOP handle after all normal handoffs.

    Never waits for the run lock or an external launch issuer. The permanent
    latch precedes cleanup; incomplete STOP propagates, without FREE/refund or
    new work permission. Only the same coordinator's current original owner is
    shut down; at most three original normal handoffs can change that pointer.
    """
    _creator(owner)
    root=owner._workflow_engineering_root
    if root is None:
        owner._actual()
        budget,pool,membership=owner.budget,owner.pool,owner.membership
        if budget._fixture_runtime is not owner:raise PermissionError('original A root owner required')
        root=(owner,owner._workflow_engineering_sequence,budget,pool,membership,owner._workflow_engineering_stop)
        owner._workflow_engineering_root=root
    else:
        if (type(root) is not tuple or len(root)!=6 or root[0] is not owner or
                root[1] is not owner._workflow_engineering_sequence or root[2] is not owner.budget or
                root[3] is not owner.pool or root[4] is not owner.membership or
                root[5] is not owner._workflow_engineering_stop):
            raise PermissionError('original A sequence STOP root required')
        _,_,budget,pool,membership,_=root
    owner._workflow_engineering_stop.set()
    for _ in range(4):
        current=budget._fixture_runtime
        if (current is None or current.budget is not budget or current.pool is not pool or
                current.membership is not membership):
            raise PermissionError('original A current coordinator owner required for STOP')
        current._safety_freeze=True
        with current._workflow_cpu_admission_lock:
            if budget._fixture_runtime is not current:continue
            ack=owner._workflow_engineering_stop_ack
            if not current._live:
                if (type(ack) is tuple and len(ack)==4 and ack[0] is root and
                        ack[1] is current and ack[2] is current.sources and not current.sources._live):
                    return json.loads(ack[3])
                return {'stop_latched':True,'status':'UNKNOWN','normal_stop_confirmed':False,
                    'reason':'NO_ORIGINAL_NORMAL_SHUTDOWN_ACK','new_work_enabled':False,'goal_completed':False}
            current._actual();current.shutdown()
            if budget._fixture_runtime is not current:continue
            from .hybrid_fixture_runtime import _owners
            if current._live or current.sources._live or id(current) in _owners:
                raise Conflict('original A normal shutdown retirement incomplete')
            result={'stop_latched':True,'status':'ORIGINAL_CURRENT_OWNER_SHUT_DOWN',
                'normal_stop_confirmed':True,'scope':'ORIGINAL_A_SEQUENCE_OWNERS',
                'financial_state':'NOT_UPGRADED','new_work_enabled':False,'goal_completed':False}
            owner._workflow_engineering_stop_ack=(root,current,current.sources,canonical(result))
            return result
    raise Conflict('original A STOP owner transition unresolved; no new work')
