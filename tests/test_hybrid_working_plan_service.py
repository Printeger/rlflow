"""Actual fresh installation + approved/prepared/HELD Working source context.

Source/material and actual nonexecuting INTENT owner tests. No model called.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from rlflow.execution_adapter import CodexExecAdapter
from rlflow.hybrid_authority import ApprovalService
from rlflow.hybrid_budget import zero
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.hybrid_budget_service import BudgetService
from rlflow.hybrid_controller_service import ControllerService
from rlflow.hybrid_drafts import DraftService
from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_goals import head_key
from rlflow.hybrid_installation_service import FixtureInstallationService
from rlflow.hybrid_preparation import intent_key
from rlflow.hybrid_preparation_service import PreparationService
from rlflow.hybrid_reads import ReadBudget
from rlflow.hybrid_snapshot import SnapshotBuilder
from rlflow.hybrid_working_copy import WorkingCopyOwner
from rlflow.hybrid_working_plan_service import WorkingPlanService
from rlflow.hybrid_workspace import fact_key, SECTIONS
from rlflow.hybrid_workspace_kernel import DirectoryHold
from rlflow.hybrid_workspace_service import WorkspaceService
from rlflow.store import Conflict, Store
from rlflow.web_auth import Principal, AuthStore, Credential
from tests.test_execution_adapter import native_config, setup as native_setup
from tests.test_hybrid_registry import bound


@pytest.fixture
def plans(tmp_path, native_setup, request, monkeypatch):
    # Native setup supplies ONLY the protected fake local catalog and version
    # stub. This fixture creates a NEW actual guarded Store/epoch/namespace;
    # it never edits or migrates any existing namespace or historical fixture.
    parent=tmp_path/'installation-parent';parent.mkdir(mode=0o700)
    options = request.param if type(getattr(request, 'param', None)) is dict else {}
    project_id = options.get('project_id', 'project_fixture')
    builder=FixtureMaterialBuilder(parent,project_id=project_id)
    installation=FixtureInstallationService(builder);material=builder.prepare()
    installation.persist_intent(material);installation.publish(material)
    store=builder.store;registry,proposal=options.get('bound', bound)(options.get('config', native_config)())
    proposal['scope']['writable_paths']=['module/']
    utc=[datetime(2026,10,9,tzinfo=timezone.utc)];mono=[100*10**9]
    human=Principal('fixture_human','human',{'operator','approver'},{project_id})
    phrase='Working plan isolated synthetic fixture passphrase'
    auth=AuthStore([Credential.create(human,phrase)],ttl=100)
    session,access=auth.login(human.id,phrase);origin='http://127.0.0.1:8765'
    args={'token':session,'csrf':access.csrf,'origin':origin}
    drafts=DraftService(store,auth,project_id=builder.project_id,data_mode='fixture',origin=origin)
    drafts.submit(proposal,**args,idempotency_key='draft',expected_revision=0,expected_state_version=store.version())
    approvals=ApprovalService(store,auth,registry,project_id=builder.project_id,data_mode='fixture',origin=origin,clock=lambda:utc[0])
    confirmation=approvals.prepare(**args,goal_id=proposal['goal_id'],ttl_seconds=60)['confirmation']
    approvals.approve(confirmation,**args,idempotency_key='approve')
    source=builder._roots['source'];(source/'module').mkdir(mode=0o700)
    (source/'module/source.py').write_text(options.get('source', 'print(42)\n'))
    control=builder._roots['bootstrap']/'preparation';control.mkdir(mode=0o700)
    adapter=CodexExecAdapter(registry,control)
    snapshots=SnapshotBuilder(source,['module/source.py'],builder._roots['snapshots'])
    prep=PreparationService(store,registry,snapshots,adapter,project_id=builder.project_id,data_mode='fixture',
        store_epoch=builder.store_epoch,clock=lambda:utc[0],monotonic_ns=lambda:mono[0])
    goal=head_key(builder.project_id,'fixture',proposal['goal_id'])
    preparation={'project_id':builder.project_id,'data_mode':'fixture','goal_ref':goal,
        'idempotency_key':'prepare','role':'Engineer','context':{'text':proposal['objective']}}
    if getattr(request,'param',False) and not options:
        schema={'type':'object','description':'Working plan literal capacity fixture',
                'examples':[{'$rlflow_blob':0} for _ in range(180000)]}
        from rlflow.store import canonical
        assert len(canonical(schema))<4*1024**2
        monkeypatch.setattr('rlflow.execution_adapter.role_schema',lambda role:schema)
    prep.prepare(preparation)
    controller=ControllerService(store,registry,project_id=builder.project_id,data_mode='fixture',
        store_epoch=builder.store_epoch,clock=lambda:utc[0],monotonic_ns=lambda:mono[0])
    acquired=controller.acquire('controller',expected_version=store.version(),ttl_seconds=60);token=acquired['token']
    budget=BudgetService(store,registry,controller,prep)
    reserve={'project_id':builder.project_id,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
        'idempotency_key':'reserve','expected_state_version':store.version(),'action':'RESERVE',
        'preparation_intent_key':intent_key(preparation),'amount':{**zero(),**options.get('amount', {'wall_seconds':1})},'purpose':'EXECUTION'}
    budget.record(reserve,token)
    working=WorkingCopyOwner(snapshots,builder._roots['working'],clock=lambda:utc[0],monotonic_ns=lambda:mono[0])
    workspace=WorkspaceService(store,registry,controller,prep,budget,working)
    observation=workspace.stage(intent_key(preparation));record=json.loads(observation.raw)
    request={'project_id':builder.project_id,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
        'idempotency_key':'workspace','expected_state_version':store.version(),'expected_workspace_revision':0,
        'workspace_id':record['workspace_id'],'reservation_id':reservation_key(reserve),'operation':'acquire','ttl_seconds':30}
    workspace.record(request,token,observation)
    owner=WorkingPlanService(workspace,installation,material)
    try:yield owner,token,observation,request,reserve,utc,mono
    finally:
        # Only uncommitted test renewals may be aborted here. No plan test below
        # hands off/registers a worker or commits a pending renewal.
        for row in tuple(working._renewals.values()):working.abort_renewal(row['pending'])
        for slot in tuple(working._issued.values()):working.close_pre_runtime(slot['observation'])
        for witness in tuple(working._closed_witnesses.values()):working.retire_closed_witness(witness)


def held(owner,observation):
    slot,_=owner.workspace.working._slot(observation)
    with pytest.raises(Conflict):DirectoryHold(slot['copy'].path)


def test_new_fixture_current_original_sources_observed_without_plan_or_runtime(plans):
    owner,token,observation,request,_,_,_=plans;before=owner.store.audit()
    result=owner.observe_sources(token,observation);value=result['sources']
    assert result['state']=='NONEXECUTING_SOURCE_OBSERVATION' and not result['execution_enabled']
    assert value['workspace_head']['fact_key']==fact_key(request)
    assert value['workspace_claim']['origin_fact_key']==fact_key(request)
    assert value['budget_reservation']['status']=='HELD' and value['observation']==json.loads(observation.raw)
    assert value['bootstrap']['installation_id']==owner.material.id
    assert owner.store.audit()==before and not owner.store.objects('jobs') and not owner.store.objects('sessions')
    assert owner._context is owner.workspace._plan_active is owner.controller._token_active is None
    assert owner.installation._bootstrap_contexts=={}
    with pytest.raises(PermissionError):owner.start(result)
    held(owner,observation)


@pytest.mark.parametrize('action',['CANCEL_BEFORE_RUNTIME','MARK_UNKNOWN'])
def test_current_budget_terminal_head_blocks_plan_source_without_releasing_fd(plans,action):
    owner,token,observation,request,reserve,_,_=plans
    command={n:reserve[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    command.update(action=action,idempotency_key='cleanup',expected_state_version=owner.store.version(),reservation_id=reservation_key(reserve))
    owner.workspace.budget.record(command,token);before=owner.store.audit()
    with pytest.raises(Conflict):owner.observe_sources(token,observation)
    assert owner.store.audit()==before;held(owner,observation)


@pytest.mark.parametrize('layer',['workspace','working'])
def test_both_pending_layers_block_sources_without_renewal_or_fd_release(plans,layer):
    owner,token,observation,_,_,_,_=plans
    pending=(owner.workspace.prepare_renewal(observation) if layer=='workspace'
             else owner.workspace.working.prepare_renewal(observation))
    with pytest.raises(Conflict,match='pending renewal'):owner.observe_sources(token,observation)
    held(owner,observation)
    assert pending.previous is observation


def test_current_close_requested_head_blocks_sources_and_keeps_fd(plans):
    owner,token,observation,request,_,_,_=plans
    closed={**request,'operation':'request_close','expected_state_version':owner.store.version(),
        'expected_workspace_revision':1,'idempotency_key':'close'};closed.pop('ttl_seconds')
    owner.workspace.record(closed,token,observation);before=owner.store.audit()
    with pytest.raises(Conflict,match='HELD_PRE_RUNTIME'):owner.observe_sources(token,observation)
    assert owner.store.audit()==before;held(owner,observation)


def test_copied_observation_unacquired_actual_slot_and_fake_owner_denied(plans):
    owner,token,observation,_,_,_,_=plans
    with pytest.raises(PermissionError):owner.observe_sources(token,replace(observation,raw=b'['*3000))
    key=json.loads(owner.workspace._issued(observation)[0]['witness'].raw)['intent_key']
    unacquired=owner.workspace.stage(key)
    with pytest.raises(Conflict,match='claim'):owner.observe_sources(token,unacquired)
    with pytest.raises(PermissionError):
        with owner.workspace._plan_context(object(),token,observation,None,None):pass
    held(owner,observation)


def test_source_files_hash_outside_business_writer(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans;calls=[]
    for component,name in ((owner.installation.builder,'verify'),(owner.workspace.preparation.builder,'verify'),
                           (owner.workspace.preparation.adapter,'verify_bundle')):
        original=getattr(component,name)
        def outside(*args,_original=original,**kwargs):
            with owner.store.lock(nonblocking=True):calls.append(True)
            return _original(*args,**kwargs)
        monkeypatch.setattr(component,name,outside)
    assert owner.observe_sources(token,observation)['execution_enabled'] is False and len(calls)>=3


@pytest.mark.parametrize('clock',['utc','mono','bootstrap'])
def test_final_source_proof_then_expiry_denies_actual_owned_commit(plans,monkeypatch,clock):
    owner,token,observation,_,_,utc,mono=plans;before=owner.store.audit()
    original=owner.workspace._check_plan_context
    def late(context):
        original(context)
        if clock=='utc':utc[0]+=timedelta(seconds=30)
        elif clock=='mono':mono[0]+=30*10**9
        else:
            from rlflow import hybrid_fixture_materials as materials
            monkeypatch.setattr(materials.time,'monotonic',lambda:context.bootstrap.inventory.deadline+1)
    monkeypatch.setattr(owner.workspace,'_check_plan_context',late)
    with pytest.raises(Conflict):owner.observe_sources(token,observation)
    assert owner.store.audit()==before and owner._context is owner.workspace._plan_active is None
    assert owner.controller._token_active is None and owner.installation._bootstrap_contexts=={}
    held(owner,observation)


def test_private_context_denies_foreign_db_and_survives_only_actual_writer(plans,tmp_path):
    owner,token,observation,_,_,_,_=plans
    slot,_=owner.workspace._issued(observation);key=json.loads(slot['witness'].raw)['intent_key']
    witness=owner.workspace.preparation.issue_material_witness(key)
    foreign=Store(tmp_path/'foreign')
    with owner.installation._bootstrap_witness(owner.material) as bootstrap:
        with owner.workspace._plan_context(owner,token,observation,witness,bootstrap) as context:
            with foreign.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                with pytest.raises(PermissionError):
                    owner.workspace._plan_sources(owner,db,ReadBudget(db),token,observation,witness,bootstrap)
            with pytest.raises(PermissionError):owner.workspace._check_plan_context(replace(context,raw=b'invalid'))
            with pytest.raises(Conflict):owner.observe_sources(token,observation)
        with pytest.raises(PermissionError):owner.workspace._check_plan_context(context)
    held(owner,observation)


def test_actual_working_plan_is_distinct_from_snapshot_and_unpublished(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans;before=owner.store.audit()
    working,_=owner.workspace.working._slot(observation)
    seed_snapshot=working['base'];old_plan=owner.workspace._issued(observation)[0]['witness'].materials[1]
    original_plan=old_plan.raw;original_snapshot=seed_snapshot.raw
    (working['copy'].path/'module/source.py').write_text('print(99)\n')
    # Current Working bytes may legitimately differ from the original snapshot.
    # This test does not run a worker or mutate the protected immutable library.
    with monkeypatch.context() as patch:
        import rlflow.isolation as isolation
        patch.setattr(isolation,'codex_command',lambda *a,**k:pytest.fail('Working plan used legacy wrapper'))
        bundle=owner.prepare_plan(token,observation,'working-original')
    actual=owner.builder.verify(bundle);plan=json.loads(actual['plan'].raw)
    assert plan['candidate']==str(working['copy'].path) and plan['candidate']!=str(seed_snapshot.path)
    assert plan['packet']['candidate_snapshot_hash']==plan['working_tree']['tree_hash']
    assert plan['write_roots']==[str(working['copy'].path/'module')]
    assert plan['working_tree']['files'][0]['bytes']==len(b'print(99)\n')
    assert old_plan.raw==original_plan and seed_snapshot.raw==original_snapshot
    assert bundle.stage_path.exists() and not bundle.path.exists()
    assert owner.prepare_plan(token,observation,'working-original') is bundle
    assert owner.store.audit()==before and not plan['execution_enabled'] and not plan['release_enabled']
    assert all(value=='UNVERIFIED' for value in plan['gates'].values())
    with pytest.raises(PermissionError):owner.builder.publish(bundle)
    with pytest.raises(PermissionError):owner.start(bundle)
    held(owner,observation)


@pytest.mark.parametrize('damage',['copy','plan_bytes','file','root_extra','empty_directory','working_changed','destination_symlink'])
def test_actual_plan_material_original_identity_and_closed_seal_denies_damage(plans,damage):
    owner,token,observation,_,_,_,_=plans;bundle=owner.prepare_plan(token,observation,'plan')
    working,_=owner.workspace.working._slot(observation)
    if damage=='copy':bundle=replace(bundle,raw=b'['*3000)
    elif damage=='plan_bytes':
        actual=owner.builder._slot(bundle)['plan'];object.__setattr__(actual,'raw',b'changed')
    elif damage=='file':(bundle.stage_path/'packet.json').write_bytes(b'changed')
    elif damage=='root_extra':(bundle.stage_path/'extra').write_bytes(b'changed')
    elif damage=='empty_directory':(bundle.stage_path/'extra').mkdir(mode=0o700)
    elif damage=='working_changed':(working['copy'].path/'module/source.py').write_text('new Working bytes')
    else:bundle.path.symlink_to('missing-destination')
    with pytest.raises((Conflict,PermissionError)):
        owner.builder.verify(bundle)
    held(owner,observation)


def test_working_plan_hash_and_writes_outside_writer_and_lost_return_original_retained(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    import rlflow.hybrid_working_plan_materials as materials
    original=materials._hash_file;calls=[]
    def outside(*args,**kwargs):
        with owner.store.lock(nonblocking=True):calls.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(materials,'_hash_file',outside)
    original_verify=owner.builder.verify
    def lost(bundle,**kwargs):original_verify(bundle,**kwargs);raise OSError('material verified but return lost')
    monkeypatch.setattr(owner.builder,'verify',lost)
    with pytest.raises(OSError,match='return lost'):owner.prepare_plan(token,observation,'original')
    assert calls and len(owner.builder._issued)==1
    bundle=next(iter(owner.builder._issued.values()))['bundle']
    monkeypatch.setattr(owner.builder,'verify',original_verify)
    assert owner.prepare_plan(token,observation,'original') is bundle
    assert owner.builder.verify(bundle)['execution_enabled'] is False


def test_failed_attempt_does_not_remint_material_or_request(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    import rlflow.hybrid_working_plan_materials as materials
    original=materials._write_at
    def fail(*args,**kwargs):original(*args,**kwargs);raise OSError('partial write')
    monkeypatch.setattr(materials,'_write_at',fail)
    with pytest.raises(OSError,match='partial write'):owner.prepare_plan(token,observation,'original')
    seed=owner._seed_keys['original'];attempt=owner.builder._attempts[seed.id]
    assert attempt['stage'].exists() and not owner.builder._issued
    with pytest.raises(Conflict,match='blocked'):owner.prepare_plan(token,observation,'original')
    assert owner._seed_keys['original'] is seed and len(owner.builder._attempts)==1
    held(owner,observation)


@pytest.mark.parametrize('damage',['file','root','empty_directory'])
def test_material_graph_stays_original_during_candidate_hash(plans,monkeypatch,damage):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original')
    original_entry=owner.builder._slot(bundle)
    working,_=owner.workspace.working._slot(observation)
    import rlflow.hybrid_working_plan_materials as materials
    original=materials._hash_file;changed=[]
    def race(item,*args,**kwargs):
        if item['path'].is_relative_to(working['copy'].path) and not changed:
            changed.append(True)
            if damage=='file':(bundle.stage_path/'packet.json').write_bytes(b'changed')
            elif damage=='empty_directory':(bundle.stage_path/'extra').mkdir(mode=0o700)
            else:
                bundle.stage_path.rename(bundle.stage_path.with_name('displaced-original'))
                bundle.stage_path.mkdir(mode=0o700)
        return original(item,*args,**kwargs)
    monkeypatch.setattr(materials,'_hash_file',race)
    with pytest.raises(Conflict):owner.builder.verify(bundle)
    assert changed and owner.builder._slot(bundle) is original_entry
    with pytest.raises(Conflict):owner.prepare_plan(token,observation,'original')
    assert len(owner.builder._attempts)==len(owner.builder._issued)==1
    held(owner,observation)


def test_build_passes_original_deadline_to_verify_before_further_io(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    import rlflow.hybrid_working_plan_materials as materials
    original_verify=owner.builder.verify;seen=[]
    def expire(bundle,**kwargs):
        deadline=kwargs['_operation_deadline'];seen.append(deadline)
        # This is the final verify of the SAME original build operation, not
        # an independent request. No inventory/hash IO may start after expiry.
        monkeypatch.setattr(materials.time,'monotonic',lambda:deadline+1)
        monkeypatch.setattr(materials,'_inventory',lambda *a,**k:pytest.fail('expired operation entered inventory'))
        return original_verify(bundle,**kwargs)
    monkeypatch.setattr(owner.builder,'verify',expire)
    with pytest.raises(Conflict):owner.prepare_plan(token,observation,'original')
    assert seen and len(owner.builder._issued)==len(owner.builder._attempts)==1
    seed=owner._seed_keys['original']
    assert owner.builder._issued[seed.id]['seed'] is seed
    held(owner,observation)


def test_material_witness_is_original_thread_scoped_nohash_and_retired(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original')
    import rlflow.hybrid_working_plan_materials as materials
    import threading
    with owner.builder._witness(bundle) as witness:
        assert witness.material_inventory and witness.candidate_inventory
        with owner.store.lock(nonblocking=True):pass
        with monkeypatch.context() as patch:
            patch.setattr(materials,'_hash_file',lambda *a,**k:pytest.fail('witness point rehashed files'))
            witness.check()
        with pytest.raises(PermissionError):replace(witness).check()
        errors=[]
        def foreign():
            try:witness.check()
            except PermissionError:errors.append(True)
        worker=threading.Thread(target=foreign);worker.start();worker.join(timeout=5)
        assert not worker.is_alive() and errors
    assert not owner.builder._witnesses
    with pytest.raises(PermissionError):witness.check()
    held(owner,observation)


@pytest.mark.parametrize('damage',['material','candidate','extra','path','deadline'])
def test_material_witness_denies_late_change_and_retires(plans,monkeypatch,damage):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original')
    import rlflow.hybrid_working_plan_materials as materials
    with owner.builder._witness(bundle) as witness:
        if damage=='material':(bundle.stage_path/'packet.json').write_bytes(b'changed')
        elif damage=='candidate':(witness.candidate/'module/source.py').write_bytes(b'changed')
        elif damage=='extra':(bundle.stage_path/'unexpected').mkdir(mode=0o700)
        elif damage=='path':bundle.stage_path.rename(bundle.path)
        else:monkeypatch.setattr(materials.time,'monotonic',lambda:witness.deadline+1)
        with pytest.raises(Conflict):witness.check()
    assert not owner.builder._witnesses
    assert owner.builder._slot(bundle)['bundle'] is bundle
    held(owner,observation)


def test_witness_captures_before_hash_and_rejects_late_verification_change(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');original=owner.builder.verify
    def after(bundle,**kwargs):
        result=original(bundle,**kwargs)
        (bundle.stage_path/'packet.json').write_bytes(b'changed after seal verification')
        return result
    monkeypatch.setattr(owner.builder,'verify',after)
    with pytest.raises(Conflict):
        with owner.builder._witness(bundle):pytest.fail('changed original graph borrowed')
    assert not owner.builder._witnesses
    held(owner,observation)


def test_writer_held_working_witness_point_never_waits_for_builder(plans):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original')
    import threading
    import time
    entered=threading.Event();release=threading.Event();errors=[]
    def other_builder():
        try:
            with owner.builder._lock:
                entered.set();release.wait(timeout=5)
        except BaseException as error:errors.append(error)
    with owner.builder._witness(bundle) as witness:
        with owner.workspace.working._lock:
            worker=threading.Thread(target=other_builder);worker.start()
            try:
                assert entered.wait(timeout=5)
                started=time.monotonic();witness.check()
                assert time.monotonic()-started<1
            finally:release.set();worker.join(timeout=5)
            assert not worker.is_alive() and not errors
    held(owner,observation)


@pytest.mark.parametrize('plans',[True],indirect=True)
def test_large_legal_literal_schema_actual_working_plan_material_and_source_context(plans):
    owner,token,observation,_,_,_,_=plans
    before=owner.store.audit()
    result=owner.observe_sources(token,observation)
    assert not result['execution_enabled']
    bundle=owner.prepare_plan(token,observation,'large-original')
    actual=owner.builder.verify(bundle)
    plan=json.loads(actual['plan'].raw)
    assert len(plan['result_schema']['examples'])==180000
    assert plan['result_schema']['examples'][0]=={'$rlflow_blob':0}
    with owner.builder._witness(bundle) as witness:witness.check()
    assert owner.store.audit()==before
    held(owner,observation)


def test_actual_original_working_plan_intent_persist_before_publish_full_closure(plans):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original-intent');version=owner.store.version()
    result=owner.persist_intent(bundle,token,observation,expected_version=version)
    assert result['version']==version+1 and not result['duplicate'] and not result['execution_enabled']
    from rlflow.hybrid_working_plan import SECTIONS
    state=owner.store.audit();assert state==owner.store.replay()
    intent=state[SECTIONS[0]][result['intent_key']]
    assert intent['plan']==json.loads(owner.builder._slot(bundle)['plan'].raw)
    assert intent['expected_seal']==json.loads(bundle.raw)['seal']
    assert SECTIONS[1] not in state and bundle.stage_path.exists() and not bundle.path.exists()
    assert owner.persist_intent(bundle,token,observation,expected_version=version)=={**result,'duplicate':True}
    assert owner.store.audit()==state
    owner.store.snapshot();assert owner.store.recover()==state
    from rlflow.snapshot_maintenance import maintain
    with owner.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(state['version'],))
    assert maintain(owner.store,seconds=30) and owner.store.recover()==state
    assert owner._active is owner._context is owner.workspace._plan_active is None
    assert not owner.builder._witnesses and not owner.installation._bootstrap_contexts
    with pytest.raises(PermissionError):owner.builder.publish(bundle)
    held(owner,observation)


@pytest.mark.parametrize('damage',['bundle_copy','token_copy','observation_copy','wrong_version','bool_version'])
def test_actual_intent_original_request_and_writer_cas_not_free_dto(plans,damage):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');before=owner.store.audit();version=before['version']
    if damage=='bundle_copy':bundle=replace(bundle,raw=b'['*3000)
    elif damage=='token_copy':token=replace(token)
    elif damage=='observation_copy':observation=replace(observation)
    elif damage=='wrong_version':version-=1
    else:version=True
    with pytest.raises((Conflict,PermissionError,ValueError)):
        owner.persist_intent(bundle,token,observation,expected_version=version)
    assert owner.store.audit()==before and not owner._intent_attempts


@pytest.mark.parametrize('phase',['before','after'])
def test_actual_intent_commit_failure_keeps_original_attempt_and_material(plans,monkeypatch,phase):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');version=owner.store.version()
    original=owner.store._commit
    def fail(*args,**kwargs):
        if phase=='after':original(*args,**kwargs)
        raise OSError('original intent event insert failure')
    monkeypatch.setattr(owner.store,'_commit',fail)
    with pytest.raises(OSError,match='insert failure'):owner.persist_intent(bundle,token,observation,expected_version=version)
    assert owner.store.version()==version and owner.builder._slot(bundle)['bundle'] is bundle
    attempt=owner._intent_attempts[bundle.id];raw=attempt['raw']
    assert owner._active is owner._context is None and not owner.builder._witnesses
    monkeypatch.setattr(owner.store,'_commit',original)
    assert not owner.persist_intent(bundle,token,observation,expected_version=version)['duplicate']
    assert owner._intent_attempts[bundle.id] is attempt and attempt['raw']==raw
    held(owner,observation)


def test_actual_intent_durable_commit_lost_return_retries_original(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');version=owner.store.version()
    original_connect=owner.store.connect
    class LostReturn:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def commit(self):
            self.db.commit()
            raise OSError('durable actual COMMIT lost return')
        def __enter__(self):return self
        def __exit__(self,*args):return self.db.__exit__(*args)
    monkeypatch.setattr(owner.store,'connect',lambda:LostReturn(original_connect()))
    with pytest.raises(OSError,match='lost return'):
        owner.persist_intent(bundle,token,observation,expected_version=version)
    monkeypatch.setattr(owner.store,'connect',original_connect)
    attempt=owner._intent_attempts[bundle.id];raw=attempt['raw']
    assert owner.store.version()==version+1 and bundle.stage_path.exists() and not bundle.path.exists()
    assert owner._active is owner._context is None and not owner.builder._witnesses
    assert not owner.installation._bootstrap_contexts
    state=owner.store.audit()
    result=owner.persist_intent(bundle,token,observation,expected_version=version)
    assert result['duplicate'] and owner.store.audit()==state
    assert owner._intent_attempts[bundle.id] is attempt and attempt['raw']==raw
    held(owner,observation)


@pytest.mark.parametrize('damage',['material','working','utc','mono'])
def test_actual_intent_final_source_then_late_damage_rolls_back_with_fd_retained(plans,monkeypatch,damage):
    owner,token,observation,_,_,utc,mono=plans
    bundle=owner.prepare_plan(token,observation,'original');before=owner.store.audit()
    original=owner.workspace._check_plan_context
    def late(context):
        original(context)
        if damage=='material':(bundle.stage_path/'packet.json').write_bytes(b'changed late')
        elif damage=='working':
            working,_=owner.workspace.working._slot(observation)
            (working['copy'].path/'module/source.py').write_bytes(b'changed late')
        elif damage=='utc':utc[0]+=timedelta(seconds=30)
        else:mono[0]+=30*10**9
    monkeypatch.setattr(owner.workspace,'_check_plan_context',late)
    with pytest.raises(Conflict):owner.persist_intent(bundle,token,observation,expected_version=before['version'])
    assert owner.store.audit()==before and owner._active is owner._context is None
    assert bundle.id in owner._intent_attempts and not owner.builder._witnesses
    held(owner,observation)


@pytest.mark.parametrize('plans',[True],indirect=True)
def test_large_legal_literal_schema_actual_intent_and_complete_closure(plans,monkeypatch):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'large-intent');version=owner.store.version()
    result=owner.persist_intent(bundle,token,observation,expected_version=version)
    from rlflow.hybrid_working_plan import SECTIONS
    state=owner.store.audit();assert owner.store.replay()==state
    assert len(state[SECTIONS[0]][result['intent_key']]['plan']['result_schema']['examples'])==180000
    owner.store.snapshot();assert owner.store.recover()==state
    from rlflow.snapshot_maintenance import maintain
    with owner.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(state['version'],))
    probes=[]
    for name in ('_preparation_event','_working_plan_event'):
        original=getattr(owner.store,name)
        def source(*args,_original=original,_name=name,**kwargs):
            probes.append((_name,kwargs.get('max_bytes')))
            try:return _original(*args,**kwargs)
            except (ValueError,Conflict) as error:
                probes.append((_name,type(error).__name__,str(error)));raise
        monkeypatch.setattr(owner.store,name,source)
    assert maintain(owner.store,seconds=30,max_bytes=64*1024**2,max_nodes=8*1024**2),probes
    assert owner.store.recover()==state
    held(owner,observation)


def test_actual_original_working_publication_retains_intent_and_no_ready(plans):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');version=owner.store.version()
    owner.persist_intent(bundle,token,observation,expected_version=version)
    state=owner.store.audit()
    result=owner._publish(bundle,token,observation)
    assert result['state']=='PUBLISHED_PENDING_READY' and not result['execution_enabled']
    assert bundle.path.is_dir() and not bundle.stage_path.exists()
    assert owner._published[bundle.id] is bundle and owner.store.audit()==state
    assert owner.builder.verify(bundle)['bundle'] is bundle
    assert owner._publish(bundle,token,observation)==result and owner.store.audit()==state
    assert not owner.builder._witnesses and not owner.builder._rebases and owner._publication_active is None
    with pytest.raises(PermissionError):owner.start(bundle)
    held(owner,observation)


@pytest.mark.parametrize('phase',['rename_before','rename_after','fsync_before','fsync_after'])
def test_actual_working_publication_unknown_retains_original_attempt(plans,monkeypatch,phase):
    import os
    from rlflow import hybrid_installation_service as installation
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');version=owner.store.version()
    owner.persist_intent(bundle,token,observation,expected_version=version);state=owner.store.audit()
    rename=installation._rename_no_replace;sync=os.fsync;parent=bundle.path.parent.stat().st_ino
    if phase.startswith('rename'):
        def failure(*args,**kwargs):
            if phase.endswith('after'):rename(*args,**kwargs)
            raise OSError('actual publication unknown rename')
        monkeypatch.setattr(installation,'_rename_no_replace',failure)
    else:
        def failure(fd):
            if os.fstat(fd).st_ino!=parent:return sync(fd)
            if phase.endswith('after'):sync(fd)
            raise OSError('actual publication unknown fsync')
        monkeypatch.setattr(os,'fsync',failure)
    with pytest.raises(OSError,match='unknown'):owner._publish(bundle,token,observation)
    attempt=owner._publication_attempts[bundle.id]
    assert owner.store.audit()==state and bundle.id not in owner._published
    assert not owner.builder._witnesses and not owner.builder._rebases and owner._publication_active is None
    monkeypatch.setattr(installation,'_rename_no_replace',rename);monkeypatch.setattr(os,'fsync',sync)
    owner._publish(bundle,token,observation)
    assert owner._publication_attempts[bundle.id] is attempt and owner._published[bundle.id] is bundle
    assert owner.store.audit()==state and bundle.path.exists() and not bundle.stage_path.exists()
    held(owner,observation)


@pytest.mark.parametrize('damage',['missing_intent','caller_move','occupied_destination','changed_child'])
def test_actual_working_publication_rejects_unowned_or_changed_material(plans,monkeypatch,damage):
    import os
    from rlflow import hybrid_installation_service as installation
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');version=owner.store.version()
    if damage!='missing_intent':owner.persist_intent(bundle,token,observation,expected_version=version)
    state=owner.store.audit()
    if damage=='caller_move':os.rename(bundle.stage_path,bundle.path)
    elif damage=='occupied_destination':
        bundle.path.mkdir(mode=0o700);(bundle.path/'sentinel').write_bytes(b'foreign destination')
    elif damage=='changed_child':
        original=installation._rename_no_replace
        def changed(*args,**kwargs):
            original(*args,**kwargs);(bundle.path/'packet.json').write_bytes(b'changed after actual rename')
        monkeypatch.setattr(installation,'_rename_no_replace',changed)
    with pytest.raises((PermissionError,Conflict)):owner._publish(bundle,token,observation)
    assert owner.store.audit()==state and bundle.id not in owner._published
    assert not owner.builder._witnesses and not owner.builder._rebases and owner._publication_active is None
    if damage=='occupied_destination':assert (bundle.path/'sentinel').read_bytes()==b'foreign destination'
    held(owner,observation)


def test_actual_working_publication_known_native_failure_then_caller_move_denied(plans,monkeypatch):
    import os
    from rlflow import hybrid_installation_service as installation
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original');version=owner.store.version()
    owner.persist_intent(bundle,token,observation,expected_version=version);state=owner.store.audit()
    original=installation._rename_no_replace
    def unavailable(*args,**kwargs):raise PermissionError('native no-replace unavailable before syscall')
    monkeypatch.setattr(installation,'_rename_no_replace',unavailable)
    with pytest.raises(PermissionError,match='unavailable'):owner._publish(bundle,token,observation)
    attempt=owner._publication_attempts[bundle.id]
    assert not attempt['receipt'].succeeded and bundle.stage_path.exists()
    os.rename(bundle.stage_path,bundle.path)
    monkeypatch.setattr(installation,'_rename_no_replace',original)
    with pytest.raises(PermissionError,match='actual owner rename'):owner._publish(bundle,token,observation)
    assert owner._publication_attempts[bundle.id] is attempt and bundle.id not in owner._published
    assert owner.store.audit()==state and not owner.builder._witnesses
    held(owner,observation)


def ready_material(plans):
    owner,token,observation,_,_,_,_=plans
    bundle=owner.prepare_plan(token,observation,'original')
    owner.persist_intent(bundle,token,observation,expected_version=owner.store.version())
    return owner,token,observation,bundle,owner.store.version()


@pytest.mark.parametrize('plans',[False,True],indirect=True)
def test_actual_ready_two_cas_publication_and_complete_closure(plans):
    owner,token,observation,bundle,version=ready_material(plans)
    result=owner.publish(bundle,token,observation,expected_version=version)
    assert result['version']==version+1 and result['state']=='PLAN_READY_NONEXECUTING'
    assert not result['execution_enabled'] and not result['release_enabled'] and not result['duplicate']
    from rlflow.hybrid_working_plan import SECTIONS
    state=owner.store.audit();assert owner.store.replay()==state
    assert len(state[SECTIONS[0]])==len(state[SECTIONS[1]])==1
    owner.store.snapshot();assert owner.store.recover()==state
    from rlflow.snapshot_maintenance import maintain
    with owner.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(state['version'],))
    schema=state[SECTIONS[0]][next(iter(state[SECTIONS[0]]))]['plan']['result_schema']
    options={'seconds':30,'max_bytes':64*1024**2,'max_nodes':8*1024**2} if schema.get('examples') else {}
    assert maintain(owner.store,**options) and owner.store.recover()==state
    assert owner.publish(bundle,token,observation,expected_version=version)['duplicate']
    assert owner.store.audit()==state and not owner.builder._rebases and not owner.builder._witnesses
    assert owner._active is owner._context is None and owner._publication_active is None
    with pytest.raises(PermissionError):owner.start(bundle)
    held(owner,observation)


@pytest.mark.parametrize('damage',['unpublished','caller_move','copy','wrong_cas'])
def test_actual_ready_requires_original_owner_publication_and_cas(plans,damage):
    import os
    owner,token,observation,bundle,version=ready_material(plans)
    if damage in ('copy','wrong_cas'):owner._publish(bundle,token,observation)
    if damage=='caller_move':os.rename(bundle.stage_path,bundle.path)
    elif damage=='copy':bundle=replace(bundle)
    elif damage=='wrong_cas':version-=1
    state=owner.store.audit()
    with pytest.raises((PermissionError,Conflict)):
        owner.persist_ready(bundle,token,observation,expected_version=version)
    assert owner.store.audit()==state and not owner._ready_attempts
    held(owner,observation)


@pytest.mark.parametrize('phase',['insert_before','insert_after','durable_commit'])
def test_actual_ready_unknown_result_preserves_original_material_request(plans,monkeypatch,phase):
    owner,token,observation,bundle,version=ready_material(plans)
    owner._publish(bundle,token,observation)
    original_commit=owner.store._commit;original_connect=owner.store.connect
    if phase=='durable_commit':
        class LostReturn:
            def __init__(self,db):self.db=db
            def __getattr__(self,name):return getattr(self.db,name)
            def commit(self):
                self.db.commit();raise OSError('actual READY durable COMMIT lost return')
            def __enter__(self):return self
            def __exit__(self,*args):return self.db.__exit__(*args)
        monkeypatch.setattr(owner.store,'connect',lambda:LostReturn(original_connect()))
    else:
        def failure(*args,**kwargs):
            if phase=='insert_after':original_commit(*args,**kwargs)
            raise OSError('actual READY insert lost return')
        monkeypatch.setattr(owner.store,'_commit',failure)
    with pytest.raises(OSError,match='lost return'):
        owner.persist_ready(bundle,token,observation,expected_version=version)
    monkeypatch.setattr(owner.store,'connect',original_connect);monkeypatch.setattr(owner.store,'_commit',original_commit)
    attempt=owner._ready_attempts[bundle.id];raw=attempt['raw']
    assert owner.store.version()==version+int(phase=='durable_commit')
    assert owner._published[bundle.id] is bundle and bundle.path.exists() and not bundle.stage_path.exists()
    assert owner._active is owner._context is None and not owner.builder._witnesses
    result=owner.persist_ready(bundle,token,observation,expected_version=version)
    assert result['duplicate']==(phase=='durable_commit')
    assert owner._ready_attempts[bundle.id] is attempt and attempt['raw']==raw and owner.store.version()==version+1
    assert owner.store.replay()==owner.store.audit()
    held(owner,observation)


@pytest.mark.parametrize('damage',['material','working','utc','mono'])
def test_actual_ready_final_source_then_late_damage_retains_original_publication(plans,monkeypatch,damage):
    owner,token,observation,bundle,version=ready_material(plans)
    owner._publish(bundle,token,observation);state=owner.store.audit()
    _,_,_,_,_,utc,mono=plans;original=owner.workspace._check_plan_context
    def late(context):
        original(context)
        if damage=='material':(bundle.path/'packet.json').write_bytes(b'late ready changed')
        elif damage=='working':
            working,_=owner.workspace.working._slot(observation)
            (working['copy'].path/'module/source.py').write_bytes(b'late working changed')
        elif damage=='utc':utc[0]+=timedelta(seconds=30)
        else:mono[0]+=30*10**9
    monkeypatch.setattr(owner.workspace,'_check_plan_context',late)
    with pytest.raises(Conflict):owner.persist_ready(bundle,token,observation,expected_version=version)
    assert owner.store.audit()==state and owner._published[bundle.id] is bundle
    assert owner._active is owner._context is None and not owner.builder._witnesses
    assert bundle.id in owner._ready_attempts
    held(owner,observation)


@pytest.mark.parametrize('phase',['commit_before','commit_after','ack_before','ack_after','rebase_before','rebase_after'])
def test_actual_publication_confirmation_unknown_keeps_original_native_receipt(plans,monkeypatch,phase):
    owner,token,observation,bundle,version=ready_material(plans)
    original_connect=owner.store.connect;ack=owner._publication_committed;rebase=owner.builder._rebase_publication
    if phase.startswith('commit'):
        class LostReturn:
            def __init__(self,db):self.db=db
            def __getattr__(self,name):return getattr(self.db,name)
            def commit(self):
                if phase=='commit_after':self.db.commit()
                raise OSError('original publication confirmation lost return')
            def __enter__(self):return self
            def __exit__(self,*args):return self.db.__exit__(*args)
        monkeypatch.setattr(owner.store,'connect',lambda:LostReturn(original_connect()))
    elif phase.startswith('ack'):
        def failure(context):
            if phase=='ack_after':ack(context)
            raise OSError('original publication confirmation lost return')
        monkeypatch.setattr(owner,'_publication_committed',failure)
    else:
        def failure(*args):
            if phase=='rebase_after':rebase(*args)
            raise OSError('original publication confirmation lost return')
        monkeypatch.setattr(owner.builder,'_rebase_publication',failure)
    with pytest.raises(OSError,match='lost return'):owner._publish(bundle,token,observation)
    monkeypatch.setattr(owner.store,'connect',original_connect);monkeypatch.setattr(owner,'_publication_committed',ack)
    monkeypatch.setattr(owner.builder,'_rebase_publication',rebase)
    attempt=owner._publication_attempts[bundle.id];receipt=attempt['receipt']
    assert receipt.succeeded and bundle.path.exists() and not bundle.stage_path.exists()
    assert (owner._published.get(bundle.id) is bundle)==(phase=='ack_after')
    assert owner._publication_pending is owner._publication_active is owner._active is owner._context is None
    assert not owner.builder._witnesses and not owner.builder._rebases and owner.store.version()==version
    owner._publish(bundle,token,observation)
    assert owner._publication_attempts[bundle.id] is attempt and attempt['receipt'] is receipt
    assert owner._published[bundle.id] is bundle and owner.store.version()==version
    held(owner,observation)


@pytest.mark.parametrize('damage',['source','material','working','utc','mono'])
def test_actual_publication_final_proof_failure_never_confirms_map(plans,monkeypatch,damage):
    owner,token,observation,bundle,version=ready_material(plans)
    _,_,_,_,_,utc,mono=plans;state=owner.store.audit();original=owner.workspace._check_plan_context
    def late(context):
        original(context)
        if damage=='source':raise Conflict('last original source proof failed')
        elif damage=='material':(bundle.path/'packet.json').write_bytes(b'late publication damage')
        elif damage=='working':
            slot,_=owner.workspace.working._slot(observation)
            (slot['copy'].path/'module/source.py').write_bytes(b'late candidate damage')
        elif damage=='utc':utc[0]+=timedelta(seconds=30)
        else:mono[0]+=30*10**9
    monkeypatch.setattr(owner.workspace,'_check_plan_context',late)
    with pytest.raises(Conflict):owner._publish(bundle,token,observation)
    assert owner.store.audit()==state and bundle.id not in owner._published
    assert owner._publication_attempts[bundle.id]['receipt'].succeeded
    assert owner._publication_pending is owner._publication_active is owner._active is owner._context is None
    assert bundle.path.exists() and not owner.builder._witnesses and not owner.builder._rebases
    held(owner,observation)


def test_actual_ready_same_original_request_two_threads_one_fact_no_deadlock(plans):
    import threading
    owner,token,observation,bundle,version=ready_material(plans)
    owner._publish(bundle,token,observation)
    start=threading.Barrier(2);results=[];errors=[]
    def writer():
        try:
            start.wait(timeout=5)
            results.append(owner.persist_ready(bundle,token,observation,expected_version=version))
        except BaseException as error:errors.append(error)
    threads=[threading.Thread(target=writer,daemon=True) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads) and not errors,errors
    assert sorted(result['duplicate'] for result in results)==[False,True]
    assert owner.store.version()==version+1 and owner.store.audit()==owner.store.replay()
    assert owner._active is owner._context is None and not owner.builder._witnesses
    held(owner,observation)


@pytest.mark.parametrize('phase',['before_publication','before_ready'])
@pytest.mark.parametrize('action',['CANCEL_BEFORE_RUNTIME','MARK_UNKNOWN'])
def test_actual_plan_current_terminal_budget_wins_without_releasing_fd(plans,phase,action):
    owner,token,observation,bundle,version=ready_material(plans)
    if phase=='before_ready':owner._publish(bundle,token,observation)
    _,_,_,_,reserve,_,_=plans
    command={n:reserve[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    command.update(action=action,idempotency_key='current-terminal',expected_state_version=version,reservation_id=reservation_key(reserve))
    owner.workspace.budget.record(command,token);state=owner.store.audit()
    with pytest.raises(Conflict):
        if phase=='before_ready':owner.persist_ready(bundle,token,observation,expected_version=version+1)
        else:owner._publish(bundle,token,observation)
    assert owner.store.audit()==state and not owner._ready_attempts
    if phase=='before_ready':assert owner._published[bundle.id] is bundle
    else:assert bundle.stage_path.exists() and bundle.id not in owner._published
    held(owner,observation)


@pytest.mark.parametrize('layer',['workspace','working'])
def test_actual_ready_both_pending_layers_block_before_attempt(plans,layer):
    owner,token,observation,bundle,version=ready_material(plans)
    owner._publish(bundle,token,observation);state=owner.store.audit()
    pending=(owner.workspace.prepare_renewal(observation) if layer=='workspace'
             else owner.workspace.working.prepare_renewal(observation))
    with pytest.raises(Conflict,match='pending renewal'):
        owner.persist_ready(bundle,token,observation,expected_version=version)
    assert pending.previous is observation and owner.store.audit()==state and not owner._ready_attempts
    held(owner,observation)


def test_actual_ready_duplicate_generic_writes_still_deny_before_existing(plans):
    from rlflow.hybrid_working_plan import SECTIONS,EVENTS
    owner,token,observation,bundle,version=ready_material(plans)
    result=owner.publish(bundle,token,observation,expected_version=version)
    state=owner.store.audit();key=result['ready_key'];value=state[SECTIONS[1]][key]
    with pytest.raises(PermissionError):
        owner.store.transact_objects(EVENTS[1],key,[(SECTIONS[1],key)],
                                    lambda projection:projection[SECTIONS[1]].update({key:value}),object_id=bundle.id)
    with pytest.raises(PermissionError):
        owner.store.transact(EVENTS[1],key,lambda projection:None,object_id=bundle.id)
    assert owner.store.audit()==state and owner._active is owner._context is None
    held(owner,observation)


def test_actual_publication_success_ack_keeps_working_plan_locks_held(plans,monkeypatch):
    import threading
    owner,token,observation,bundle,version=ready_material(plans)
    original=owner._publication_committed;probes=[]
    def ack(context):
        assert context is owner._context and context.db.in_transaction is False
        def competing():
            for lock in (owner.workspace._lock,owner.workspace.working._lock,owner._lock):
                acquired=lock.acquire(timeout=.05);probes.append(acquired)
                if acquired:lock.release()
        thread=threading.Thread(target=competing,daemon=True);thread.start();thread.join(timeout=2)
        assert not thread.is_alive() and probes==[False,False,False]
        assert owner._publication_pending is not None and owner._published.get(bundle.id) is None
        original(context)
    monkeypatch.setattr(owner,'_publication_committed',ack)
    owner._publish(bundle,token,observation)
    assert probes==[False,False,False] and owner._published[bundle.id] is bundle
    assert owner.store.version()==version and owner._publication_pending is None
    held(owner,observation)


def test_actual_publication_and_ready_allow_unrelated_core_versions_not_changed_heads(plans):
    owner,token,observation,bundle,version=ready_material(plans)
    owner.store.transact_objects('HISTORY','before-publish',[('historical','before')],
                                lambda state:state['historical'].update(before={'value':1}))
    owner._publish(bundle,token,observation)
    owner.store.transact_objects('HISTORY','before-ready',[('historical','after')],
                                lambda state:state['historical'].update(after={'value':2}))
    result=owner.persist_ready(bundle,token,observation,expected_version=version+2)
    assert result['version']==version+3 and not result['execution_enabled']
    assert owner.store.audit()==owner.store.replay()
    assert owner.persist_ready(bundle,token,observation,expected_version=version+2)['duplicate']
    held(owner,observation)


@pytest.mark.parametrize('version_kind',['wrong','boolean'])
def test_actual_public_publish_wrong_cas_cannot_move_stage_or_bind_attempt(plans,version_kind):
    owner,token,observation,bundle,version=ready_material(plans);state=owner.store.audit()
    with pytest.raises((Conflict,ValueError)):
        owner.publish(bundle,token,observation,expected_version=True if version_kind=='boolean' else version-1)
    assert bundle.stage_path.exists() and not bundle.path.exists()
    assert not owner._publication_attempts and not owner._ready_attempts and not owner._published
    assert owner.store.audit()==state and not owner.builder._witnesses
    held(owner,observation)
