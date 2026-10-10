"""Fresh isolated configurable CPU Core session; no production or model grant.

Synthetic development confirmation is not independent product Review. Only the
original approved spec receives the Core-gated local CPU execution capability.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import secrets

from .isolated_finite_example import (profile as fixed_profile,Registry,FixtureMaterialBuilder,
    FixtureInstallationService,HostPoolOwner,AuthStore,Credential,Principal,DraftService,
    ApprovalService,CodexExecAdapter,SnapshotBuilder,PreparationService,head_key,intent_key,
    ControllerService,BudgetService,zero,reservation_key,WorkingCopyOwner,WorkspaceService,
    WorkingPlanService,digest)
from .hybrid_fixture_materials import _write_new
from .hybrid_local_cpu_profile import validate_spec, registration, module_pins
from .hybrid_local_cpu_runtime import LocalCpuRunnerOwner


def profile(project,spec):
    spec=validate_spec(spec);_,proposal=fixed_profile(project,'cpu_trial')
    registered=registration(spec,module_pins())
    config={'schema_version':'1.0','project_id':project,'data_mode':'fixture',
        'tools':{'local_cpu':registered['tool']},'commands':{'local_cpu':registered['command']},
        'runtime_profile':{'adapter':'codex-exec','model':'gpt-6.1-sol','effort':'medium',
            'codex_version':'0.161.0','native_subagents':False,'cpu_network':'none',
            'memory_bytes':spec['limits']['memory_max'],'command_seconds':spec['seconds']},
        'resource_profile':registered['resources'],'datasets':{},
        'evaluation_rules':{'local_cpu_rule':registered['rule']},
        'project_policy':{'network_access':'none','allowed_hosts':[],
            'configuration':{'protected_control':'external','execution_enabled':False}}}
    registry=Registry(config)
    proposal.update(objective='Original configured local CPU task with managed STOP',
        goal_kind=spec['purpose'],allowed_tools=['local_cpu'],registry_bindings=registry.bindings,
        evaluation_data={'mode':'EXPLICIT_NONE','datasets':[],
            'evaluation_rule':{'id':'local_cpu_rule','version_hash':digest(registered['rule'])}})
    proposal['global_conditions'][0]['description']='Configured local machine verification passes; not independent review'
    proposal['global_conditions'][0]['verification']['rule']='Original approved configured result; NOT_CONFIGURED is not PASS'
    proposal['scope']['allowed_command_templates']=['local_cpu']
    proposal['budget']['experiment_starts']=3 if spec['purpose']=='research' else 0
    # Maintain the original finalization floor; ensure execution reservation
    # fits available balance, rather than weakening arithmetic to accept it.
    proposal['budget']['wall_seconds']=max(300,2*(spec['seconds']+10))
    proposal['stop_rules']=['Original configured CPU only; no model/GPU',
                            'Keep UNKNOWN on missing original managed terminal proof']
    return registry,proposal


@contextmanager
def isolated_session(parent,spec,*,approved=False,confirmation_reader=None):
    if approved is not True:raise PermissionError('explicit isolated configured CPU consent required')
    parent=Path(parent).resolve(strict=True)
    if parent.stat().st_mode&0o077:raise PermissionError('existing private isolated parent required')
    project='isolated_local_cpu';pool=HostPoolOwner.create_fixture(parent)
    runtime=working=None
    try:
        registered_parent=pool.projects_root/project;registered_parent.mkdir(mode=0o700)
        builder=FixtureMaterialBuilder(registered_parent,project_id=project)
        installation=FixtureInstallationService(builder);material=builder.prepare()
        installation.persist_intent(material);installation.publish(material)
        store=builder.store;registry,proposal=profile(project,spec)
        phrase=secrets.token_urlsafe(40)
        principal=Principal('local_cpu_fixture_operator','human',{'operator','approver'},{project})
        auth=AuthStore([Credential.create(principal,phrase)])
        human,access=auth.login(principal.id,phrase);origin='http://127.0.0.1:8765'
        authority={'token':human,'csrf':access.csrf,'origin':origin}
        draft=DraftService(store,auth,project_id=project,data_mode='fixture',origin=origin)
        approval=ApprovalService(store,auth,registry,project_id=project,data_mode='fixture',origin=origin)
        draft.submit(proposal,**authority,idempotency_key='cpu_draft',expected_revision=0,expected_state_version=store.version())
        confirmation=approval.prepare(**authority,goal_id=proposal['goal_id'],ttl_seconds=300)['confirmation']
        print(json.dumps({'proposal':proposal,'approval_scope_hash':confirmation['scope_hash']}),flush=True)
        print('Type APPROVE '+confirmation['scope_hash']+' for ONLY this isolated zero-model/GPU CPU spec:',flush=True)
        answer=(__import__('sys').stdin.readline(90) if confirmation_reader is None else confirmation_reader(proposal,confirmation))
        if answer.strip()!='APPROVE '+confirmation['scope_hash']:
            raise PermissionError('original exact configured CPU scope not confirmed')
        approval.approve(confirmation,**authority,idempotency_key='cpu_approve')
        source=builder._roots['source'];(source/'module').mkdir(mode=0o700)
        _write_new(source/'module/source.py',validate_spec(spec)['code'].encode())
        prep_root=builder._roots['bootstrap']/'preparation';prep_root.mkdir(mode=0o700)
        adapter=CodexExecAdapter(registry,prep_root)
        snapshots=SnapshotBuilder(source,['module/source.py'],builder._roots['snapshots'])
        prep=PreparationService(store,registry,snapshots,adapter,project_id=project,data_mode='fixture',store_epoch=builder.store_epoch)
        goal=head_key(project,'fixture',proposal['goal_id'])
        request={'project_id':project,'data_mode':'fixture','goal_ref':goal,'idempotency_key':'prepare',
            'role':'Engineer','context':{'text':proposal['objective']}}
        prep.prepare(request)
        controller=ControllerService(store,registry,project_id=project,data_mode='fixture',store_epoch=builder.store_epoch)
        token=controller.acquire('controller',expected_version=store.version(),ttl_seconds=60)['token']
        budget=BudgetService(store,registry,controller,prep)
        spec=validate_spec(spec)
        reserve={'project_id':project,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
            'idempotency_key':'reserve','expected_state_version':store.version(),'action':'RESERVE',
            'preparation_intent_key':intent_key(request),'amount':{**zero(),'wall_seconds':spec['seconds']+10,
                'experiment_starts':int(spec['purpose']=='research')},'purpose':'EXECUTION'}
        budget.record(reserve,token)
        working=WorkingCopyOwner(snapshots,builder._roots['working'])
        workspace=WorkspaceService(store,registry,controller,prep,budget,working)
        observation=workspace.stage(intent_key(request),ttl_seconds=60);observed=json.loads(observation.raw)
        workspace.record({'project_id':project,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
            'idempotency_key':'workspace','expected_state_version':store.version(),'expected_workspace_revision':0,
            'workspace_id':observed['workspace_id'],'reservation_id':reservation_key(reserve),
            'operation':'acquire','ttl_seconds':60},token,observation)
        plans=WorkingPlanService(workspace,installation,material)
        membership=pool.register_project(installation,material,expected_version=pool.snapshot()['version'])
        runtime=LocalCpuRunnerOwner(pool,membership,plans)
        bundle=plans.prepare_plan(token,observation,'local_cpu_plan')
        plans.persist_intent(bundle,token,observation,expected_version=store.version())
        plans.publish(bundle,token,observation,expected_version=store.version())
        claim=pool.claim(membership,expected_version=pool.snapshot()['version'],request_key='cpu_claim',seconds=60)
        grant=runtime.issue_local_cpu_grant(bundle,token,observation)
        lease=runtime.register(bundle,token,observation,claim,request_key='cpu_lease',scenario='local_cpu',local_cpu_grant=grant)
        yield {'runtime':runtime,'lease':lease,'grant':grant,'bundle':bundle,'token':token,
               'observation':observation,'claim':claim,'reserve':reserve,'adapter':adapter,'plans':plans}
    finally:
        errors=[]
        if runtime is not None and runtime._live:
            try:runtime.shutdown()
            except BaseException as exc:
                errors.append(exc)
                if runtime._live:
                    try:runtime.shutdown_safety()
                    except BaseException as cleanup:errors.append(cleanup)
        if working is not None:
            for slot in tuple(working._issued.values()):
                try:working.close_pre_runtime(slot['observation'])
                except BaseException as exc:errors.append(exc)
            for witness in tuple(working._closed_witnesses.values()):
                try:working.retire_closed_witness(witness)
                except BaseException as exc:errors.append(exc)
        if pool._live:
            try:pool.shutdown()
            except BaseException as exc:errors.append(exc)
        active=__import__('sys').exc_info()[1]
        if errors and active is not None:
            for error in errors:active.add_note('original local CPU cleanup incomplete: '+str(error))
        elif errors:raise errors[0]


def main(argv=None):
    """Public installed local-only entry; history never resumes execution."""
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('run',help='Fresh isolated approved configurable CPU task')
    run.add_argument('--parent',type=Path,required=True)
    run.add_argument('--spec',type=Path,required=True)
    run.add_argument('--approve-isolated-local-cpu',action='store_true')
    history=commands.add_parser('history',help='Read original facts; no handles, STOP or execution replay')
    history.add_argument('--root',type=Path,required=True)
    history.add_argument('--store-epoch',required=True)
    history.add_argument('--reservation-id',required=True)
    history.add_argument('--recover-task-evidence',action='store_true',
        help='Read original durable keeper report and sealed outputs; no replay, STOP or settlement')
    args=parser.parse_args(argv)
    if args.command=='history':
        from .store import Store
        from .hybrid_local_cpu_reads import LocalCpuTaskReader
        store=Store.attach_existing(args.root,project_id='isolated_local_cpu',data_mode='fixture')
        reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=args.store_epoch)
        value=(reader.recover_task_evidence(args.reservation_id) if args.recover_task_evidence else
               reader.task(args.reservation_id,timeline=True))
        if value is None:parser.error('original configured CPU reservation not found')
        print(json.dumps(value,sort_keys=True),flush=True)
        return 0
    if not args.approve_isolated_local_cpu:
        parser.error('explicit isolated zero-model/GPU CPU consent required; exact scope confirmation follows')
    # Bound before parsing and freeze bytes before any authority/installation.
    # File changes after this read cannot replace the approved spec.
    with args.spec.open('rb') as source:raw=source.read(256*1024+1)
    if len(raw)>256*1024:parser.error('configured CPU spec file exceeds 256 KiB')
    def unique_fields(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('duplicate configured CPU spec field')
            value[key]=item
        return value
    spec=validate_spec(json.loads(raw,object_pairs_hook=unique_fields))
    with isolated_session(args.parent,spec,approved=True) as session:
        runtime=session['runtime'];lease=session['lease']
        locator={'root':str(runtime.store.root),'store_epoch':runtime.plans.workspace.store_epoch,
                 'reservation_id':reservation_key(session['reserve'])}
        # Emit recovery selector before G, including failures after handoff.
        print(json.dumps({'historical_recovery':locator,'cold_execution_replay':False}),flush=True)
        result=None
        execution_failed=False
        try:result=runtime.run_local_cpu(lease)
        except Exception:
            # run_local_cpu's finally already attempted the original STOP.
            # A failed task is not a machine FAIL verdict or a new retry.
            # Context cleanup below must still succeed before final reporting;
            # if it cannot, only the earlier recovery selector was published.
            execution_failed=True
        from .hybrid_local_cpu_reads import LocalCpuTaskReader
        reader=LocalCpuTaskReader(runtime.store,project_id='isolated_local_cpu',store_epoch=locator['store_epoch'])
        report={'historical_recovery':locator,'result':result,
                'history':reader.task(locator['reservation_id'],timeline=True),
                'pool_after':runtime.pool.snapshot(),'model_calls':0,'gpu_calls':0,
                'autonomous_goal_complete':False,
                'execution_outcome':'FAILED_NO_RESULT' if execution_failed else 'RESULT_ARCHIVED'}
    # Success is printed only after original context cleanup succeeds.
    print(json.dumps(report,sort_keys=True),flush=True)
    if execution_failed:return 3
    return {'PASS':0,'FAIL':1,'NOT_CONFIGURED':2}[result['machine_acceptance']['status']]


if __name__=='__main__':
    raise SystemExit(main())
