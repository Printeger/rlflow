"""Disposable original SDK native→held local receiver→STOP→ledger readback.

Run only with --approve-isolated-local-diagnostic in an existing private parent.
No model server, credentials, real tokens, tools, GPU or live-project execution.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from .isolated_finite_example import (profile as fixed_profile,Registry,FixtureMaterialBuilder,
    FixtureInstallationService,HostPoolOwner,AuthStore,Credential,Principal,DraftService,
    ApprovalService,CodexExecAdapter,SnapshotBuilder,PreparationService,head_key,intent_key,
    ControllerService,BudgetService,zero,reservation_key,WorkingCopyOwner,WorkspaceService,
    WorkingPlanService,digest)
from .hybrid_native_diagnostic import NativeDiagnosticOwner,pin_binary,registration,KIND,AUTHORIZATION
from .hybrid_fixture_runtime_reads import FixtureTaskReader
from .store import Conflict


def profile(project):
    """Brand-new closed approval; never upgrade an existing fixed fixture."""
    _,proposal=fixed_profile(project,'cpu_trial')
    package=Path(__file__).parent
    pins=['sha256:'+hashlib.sha256((package/name).read_bytes()).hexdigest()
          for name in ('hybrid_native_diagnostic_gate.py','hybrid_native_diagnostic.py')]
    row=pin_binary()
    try:registered=registration(*pins,row['sha256'])
    finally:os.close(row['fd'])
    config={'schema_version':'1.0','project_id':project,'data_mode':'fixture',
        'tools':{'native_diagnostic':registered['tool']},'commands':{'native_diagnostic':registered['command']},
        'runtime_profile':{'adapter':'codex-exec','model':'gpt-6.1-sol','effort':'medium','codex_version':'0.161.0',
            'native_subagents':False,'cpu_network':'none','memory_bytes':128*1024**2,'command_seconds':20},
        'resource_profile':registered['resources'],'datasets':{},
        'evaluation_rules':{'native_diagnostic_rule':registered['rule']},
        'project_policy':{'network_access':'allowlist','allowed_hosts':['127.0.0.1'],
            'configuration':{'protected_control':'external','execution_enabled':False}}}
    registry=Registry(config)
    proposal.update(objective='Original native CLI local non-generating inflight STOP diagnostic',goal_kind='engineering',
        allowed_tools=['native_diagnostic'],registry_bindings=registry.bindings,
        evaluation_data={'mode':'EXPLICIT_NONE','datasets':[],
            'evaluation_rule':{'id':'native_diagnostic_rule','version_hash':digest(registered['rule'])}})
    proposal['scope'].update(allowed_command_templates=['native_diagnostic'],network_access='allowlist',allowed_hosts=['127.0.0.1'])
    proposal['budget']['experiment_starts']=0
    proposal['stop_rules']=['Only local non-generating native diagnostic','No real model, credentials, GPU or tools']
    return registry,proposal


class NativeDiagnosticReader(FixtureTaskReader):
    _accepted_origin_kind=KIND

    @staticmethod
    def _dto(key,head):
        value=FixtureTaskReader._dto(key,head)
        value.update(kind=KIND,authorization=AUTHORIZATION,local_native_diagnostic=True,
            recorded_scope='FIXED_NATIVE_SINGLE_TGID',model_access_verified=False,
            usage_status='NOT_PROVIDED',network_enforcement='PARTIAL')
        return value


@contextmanager
def isolated_session(parent,*,approved=False,confirmation_reader=None):
    """Fresh fixture-domain session; operator's explicit local-diagnostic consent."""
    if approved is not True:raise PermissionError('explicit isolated local diagnostic consent required')
    parent=Path(parent).resolve(strict=True)
    if parent.stat().st_mode&0o077:raise PermissionError('existing private isolated parent required')
    project='isolated_native_diagnostic';pool=HostPoolOwner.create_fixture(parent)
    runtime=None;working=None
    try:
        registered_parent=pool.projects_root/project;registered_parent.mkdir(mode=0o700)
        builder=FixtureMaterialBuilder(registered_parent,project_id=project)
        installation=FixtureInstallationService(builder);material=builder.prepare()
        installation.persist_intent(material);installation.publish(material)
        store=builder.store;registry,proposal=profile(project)
        phrase=secrets.token_urlsafe(40);principal=Principal('diagnostic_fixture_operator','human',{'operator','approver'},{project})
        auth=AuthStore([Credential.create(principal,phrase)])
        human,access=auth.login(principal.id,phrase);origin='http://127.0.0.1:8765'
        authority={'token':human,'csrf':access.csrf,'origin':origin}
        draft=DraftService(store,auth,project_id=project,data_mode='fixture',origin=origin)
        approval=ApprovalService(store,auth,registry,project_id=project,data_mode='fixture',origin=origin)
        draft.submit(proposal,**authority,idempotency_key='diagnostic_draft',expected_revision=0,expected_state_version=store.version())
        confirmation=approval.prepare(**authority,goal_id=proposal['goal_id'],ttl_seconds=300)['confirmation']
        print(json.dumps({'proposal':proposal,'approval_scope_hash':confirmation['scope_hash'],
            'consent_ttl_seconds':300}),flush=True)
        print('Type APPROVE '+confirmation['scope_hash']+' to approve ONLY this disposable local non-model diagnostic:',flush=True)
        answer=(__import__('sys').stdin.readline(90) if confirmation_reader is None else confirmation_reader(proposal,confirmation))
        if answer.strip()!='APPROVE '+confirmation['scope_hash']:
            raise PermissionError('original exact scope not confirmed; no execution')
        approval.approve(confirmation,**authority,idempotency_key='diagnostic_approve')
        source=builder._roots['source'];(source/'module').mkdir(mode=0o700)
        from .hybrid_fixture_materials import _write_new
        _write_new(source/'module/source.py',b'# Local diagnostic only; never executes this candidate.\n')
        prep_root=builder._roots['bootstrap']/'preparation';prep_root.mkdir(mode=0o700)
        adapter=CodexExecAdapter(registry,prep_root);snapshots=SnapshotBuilder(source,['module/source.py'],builder._roots['snapshots'])
        prep=PreparationService(store,registry,snapshots,adapter,project_id=project,data_mode='fixture',store_epoch=builder.store_epoch)
        goal=head_key(project,'fixture',proposal['goal_id'])
        request={'project_id':project,'data_mode':'fixture','goal_ref':goal,'idempotency_key':'prepare',
            'role':'Engineer','context':{'text':proposal['objective']}}
        prep.prepare(request)
        controller=ControllerService(store,registry,project_id=project,data_mode='fixture',store_epoch=builder.store_epoch)
        token=controller.acquire('controller',expected_version=store.version(),ttl_seconds=60)['token']
        budget=BudgetService(store,registry,controller,prep)
        reserve={'project_id':project,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
            'idempotency_key':'reserve','expected_state_version':store.version(),'action':'RESERVE',
            'preparation_intent_key':intent_key(request),'amount':{**zero(),'wall_seconds':20},'purpose':'EXECUTION'}
        budget.record(reserve,token)
        working=WorkingCopyOwner(snapshots,builder._roots['working'])
        workspace=WorkspaceService(store,registry,controller,prep,budget,working)
        observation=workspace.stage(intent_key(request),ttl_seconds=60);observed=json.loads(observation.raw)
        workspace.record({'project_id':project,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
            'idempotency_key':'workspace','expected_state_version':store.version(),'expected_workspace_revision':0,
            'workspace_id':observed['workspace_id'],'reservation_id':reservation_key(reserve),'operation':'acquire','ttl_seconds':60},token,observation)
        plans=WorkingPlanService(workspace,installation,material)
        membership=pool.register_project(installation,material,expected_version=pool.snapshot()['version'])
        runtime=NativeDiagnosticOwner(pool,membership,plans)
        bundle=plans.prepare_plan(token,observation,'diagnostic_plan')
        plans.persist_intent(bundle,token,observation,expected_version=store.version())
        plans.publish(bundle,token,observation,expected_version=store.version())
        claim=pool.claim(membership,expected_version=pool.snapshot()['version'],request_key='diagnostic_claim',seconds=60)
        grant=runtime.issue_diagnostic_grant(bundle,token,observation)
        lease=runtime.register(bundle,token,observation,claim,request_key='diagnostic_lease',scenario='native_diagnostic',diagnostic_grant=grant)
        yield {'runtime':runtime,'lease':lease,'reservation_id':reservation_key(reserve),'scope_hash':confirmation['scope_hash'],
            'reader':NativeDiagnosticReader(store,project_id=project,store_epoch=builder.store_epoch),'adapter':adapter,'plans':plans}
    finally:
        errors=[]
        if runtime is not None and runtime._live:
            try:runtime.shutdown()
            except BaseException as error:
                errors.append(error)
                if runtime._live:
                    try:runtime.shutdown_safety()
                    except BaseException as cleanup:errors.append(cleanup)
        if working is not None:
            for slot in tuple(working._issued.values()):
                try:working.close_pre_runtime(slot['observation'])
                except BaseException as error:errors.append(error)
            for witness in tuple(working._closed_witnesses.values()):
                try:working.retire_closed_witness(witness)
                except BaseException as error:errors.append(error)
        if pool._live:
            try:pool.shutdown()
            except BaseException as error:errors.append(error)
        active=__import__('sys').exc_info()[1]
        if errors and active is not None:
            for error in errors:active.add_note('original diagnostic cleanup incomplete: '+type(error).__name__+': '+str(error))
        elif errors:raise errors[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--approve-isolated-local-diagnostic',action='store_true')
    args=parser.parse_args()
    if not args.approve_isolated_local_diagnostic:parser.error('explicit local diagnostic consent required')
    with isolated_session(args.parent,approved=True) as session:
        runtime=session['runtime'];lease=session['lease'];runtime.start(lease)
        source=runtime.sources._issued(runtime._issued(lease)['source'])
        deadline=time.monotonic()+5;value=None
        while time.monotonic()<deadline:
            value=runtime.poll(lease)
            if source['received'].is_set() and value['phase']=='STARTED_AS_OBSERVED':break
            if source['producer'].poll() is not None:raise Conflict('native exited before inflight diagnostic STOP')
            time.sleep(.01)
        else:raise RuntimeError('native diagnostic request/start observation deadline exceeded')
        before=runtime.pool.snapshot();stop=runtime.stop_to_terminal(lease)
        report=session['reader'].task(session['reservation_id'],timeline=True)
        print(json.dumps({'approval_scope_hash':session['scope_hash'],'before_stop':value,'stop':stop,
            'original_terminal':runtime._issued(lease)['terminal'],'report':report,
            'pool_before':before,'pool_after':runtime.pool.snapshot(),
            'receiver_requests':source['receiver_requests'],'model_calls':0,'gpu_calls':0,
            'test_modules_imported':any(n=='tests' or n.startswith('tests.') for n in __import__('sys').modules)},sort_keys=True),flush=True)


if __name__=='__main__':main()
