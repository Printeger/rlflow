"""Real fixed read-only worker -> STOP/FREE -> one core write and audit output."""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

import pytest

from rlflow.hybrid_engineering_patch import registration,BEFORE,AFTER,TARGET
from rlflow.hybrid_candidate_output import SECTIONS,EVENTS,intent_key,result_key,validate_record,validate_links,validate_transition
from rlflow.hybrid_candidate_output_service import CandidateOutputService
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict,canonical,sha
from tests import test_hybrid_working_plan_service as plan_module
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_fixture_runtime import runtime,_FIXED_CPU_POPEN


@pytest.fixture
def engineering_runtime(tmp_path,native_setup,request,monkeypatch):
    root=Path(__file__).resolve().parents[1]/'rlflow'
    pins=['sha256:'+hashlib.sha256((root/name).read_bytes()).hexdigest()
        for name in ('hybrid_engineering_fixture.py','hybrid_engineering_patch.py')]
    registered=registration(*pins);native_config,bound=plan_module.native_config,plan_module.bound
    def config():
        value=native_config()
        value['tools']['engineering_patch']=registered['tool']
        value['commands']['engineering_patch']=registered['command']
        value['evaluation_rules']['engineering_patch_rule']=registered['rule']
        value['resource_profile']=registered['resources'];return value
    def proposal(configuration):
        registry,value=bound(configuration)
        value.update(goal_kind='engineering',objective='Repair exact add subtraction bug; validate actual candidate without model/GPU.')
        value['allowed_tools']=['engineering_patch'];value['scope']['allowed_command_templates']=['engineering_patch']
        value['evaluation_data']={'mode':'EXPLICIT_NONE','datasets':[],
            'evaluation_rule':{'id':'engineering_patch_rule','version_hash':digest(registered['rule'])}}
        for key in ('model_sessions','model_input_tokens','model_output_tokens','gpu_device_seconds','experiment_starts','experiment_retries'):
            value['budget'][key]=0
        return registry,value
    write_text=Path.write_text
    def original_source(path,data,*args,**kwargs):
        if path.name=='source.py' and path.parent.name=='module' and data=='print(42)\n':data=BEFORE.decode()
        return write_text(path,data,*args,**kwargs)
    monkeypatch.setattr(plan_module,'native_config',config);monkeypatch.setattr(plan_module,'bound',proposal)
    monkeypatch.setattr(Path,'write_text',original_source)
    fixture=runtime.__wrapped__(tmp_path,native_setup,request,monkeypatch);context=next(fixture)
    def fixed_only(argv,**kwargs):
        assert argv[:4]==[sys.executable,'-B','-I','-S']
        assert len(argv)==9 and argv[4].startswith('/proc/self/fd/') and argv[7]=='engineering_patch'
        assert kwargs['pass_fds']==(int(argv[4].rsplit('/',1)[1]),int(argv[8]))
        return _FIXED_CPU_POPEN(argv,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',fixed_only)
    try:yield context
    finally:fixture.close()


def engineering_lease(context):
    owner,bundle,token,observation,claim,*_=context
    grant=owner.issue_engineering_patch_grant(bundle,token,observation)
    lease=owner.register(bundle,token,observation,claim,request_key='engineering',scenario='engineering_patch',engineering_grant=grant)
    return grant,lease


def test_actual_fixed_engineering_candidate_write_stop_output_and_recovery(engineering_runtime,monkeypatch):
    owner,bundle,token,observation,*_=engineering_runtime
    grant,lease=engineering_lease(engineering_runtime);attempt=owner._issued(lease)
    slot,_=owner.workspace.working._slot(observation);path=slot['copy'].path/TARGET
    before_inode=(path.stat().st_dev,path.stat().st_ino);plan_before=(bundle.path/'module/source.py').read_bytes() if (bundle.path/'module/source.py').exists() else None
    result=owner.run_engineering_patch(lease);proposal=json.loads(result.raw)
    assert proposal['baseline_failed_cases']==2 and proposal['repaired_passed_cases']==3
    assert proposal['candidate_write_performed'] is False and path.read_bytes()==BEFORE
    assert owner.pool.snapshot()['occupied']==0
    assert owner._engineering_grants[id(grant)]['fd'] is None
    assert attempt['terminal']['program_sha256']==attempt['origin']['program_sha256']!=owner.program_hash
    source=owner.sources._issued(attempt['source'])
    assert source['producer'].returncode==0 and all(fd is None for fd in source['fds'].values())
    service=CandidateOutputService(owner);writes=[];pwrite=os.pwrite
    def bounded(fd,data,offset):writes.append((data,offset));return pwrite(fd,data,offset)
    monkeypatch.setattr(os,'pwrite',bounded)
    accepted=service.apply(lease,token,idempotency_key='repair',expected_state_version=owner.store.version())
    value=accepted['fact'];key=result_key(value['request'])
    assert not accepted['duplicate'] and value['state']=='OUTPUT_CAPTURED_AUDIT_ONLY'
    assert path.read_bytes()==AFTER and (path.stat().st_dev,path.stat().st_ino)==before_inode
    assert writes==[(AFTER,0)] and value['candidate_write_fd_closed'] is True
    assert value['goal_completed'] is False and value['independent_review_status']=='NOT_PERFORMED'
    assert [row['actual'] for row in value['actual_tests']]==[5,-2,0]
    if plan_before is not None:assert (bundle.path/'module/source.py').read_bytes()==plan_before
    version=owner.store.version();assert service.reconcile(lease)['duplicate']
    assert owner.store.version()==version and len(writes)==1 and owner.store.get(SECTIONS[1],key)==value
    state=owner.store.audit();assert owner.store.replay()==state
    owner.store.snapshot();assert owner.store.recover()==state
    print('actual_fixed_engineering_output',json.dumps({'baseline_failed':2,'actual_tests':value['actual_tests'],
        'single_pwrite':len(writes),'base_hash':value['base_tree']['tree_hash'],'output_hash':value['output_tree']['tree_hash'],
        'pool_occupied':owner.pool.snapshot()['occupied'],'goal_completed':False}))


def stopped(context):
    owner=context[0];_,lease=engineering_lease(context);owner.run_engineering_patch(lease)
    service=CandidateOutputService(owner)
    return owner,lease,service,{'idempotency_key':'repair','expected_state_version':owner.store.version()}


def test_actual_lost_physical_write_return_reconcile_after_expiry_without_rewrite(engineering_runtime,monkeypatch):
    owner,lease,service,args=stopped(engineering_runtime);token=engineering_runtime[2]
    utc,mono=engineering_runtime[-2:];pwrite=os.pwrite;writes=[]
    def lost(fd,data,offset):
        writes.append(True);pwrite(fd,data,offset);raise OSError('actual pwrite lost return')
    with monkeypatch.context() as patch:
        patch.setattr(os,'pwrite',lost)
        with pytest.raises(OSError,match='lost return'):service.apply(lease,token,**args)
    row=service._rows[id(lease)];material=row['material']
    assert material.write_entered and material.fd is not None and not material.closed
    assert owner.store.objects(SECTIONS[1])==[] and owner.pool.snapshot()['occupied']==0
    utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9
    monkeypatch.setattr(os,'pwrite',lambda *a:pytest.fail('receipt must not repeat physical write'))
    value=service.reconcile(lease)['fact']
    assert value['recorded_at']>value['sources']['expires_at'] and material.fd is None and material.closed
    assert service.reconcile(lease)['duplicate'] and writes==[True]
    assert owner.store.audit()==owner.store.replay()
    with pytest.raises(Conflict,match='reconcile'):service.apply(lease,token,**args)


@pytest.mark.parametrize('phase',['intent','result'])
def test_actual_lost_commit_return_keeps_original_cap_and_single_write(engineering_runtime,monkeypatch,phase):
    owner,lease,service,args=stopped(engineering_runtime);store=owner.store;token=engineering_runtime[2]
    connect=store.connect;lost=[];pwrite=os.pwrite;writes=[]
    def counted(fd,data,offset):writes.append(True);return pwrite(fd,data,offset)
    monkeypatch.setattr(os,'pwrite',counted)
    wanted=EVENTS[0 if phase=='intent' else 1]
    class LostReturn:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def __enter__(self):return self
        def __exit__(self,*args):return self.db.__exit__(*args)
        def commit(self):
            event=self.db.execute('SELECT event_type FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0]
            self.db.commit()
            if event==wanted and not lost:lost.append(True);raise OSError('actual candidate COMMIT lost receipt')
    with monkeypatch.context() as patch:
        patch.setattr(store,'connect',lambda:LostReturn(connect()))
        with pytest.raises(OSError,match='lost receipt'):service.apply(lease,token,**args)
    assert lost==[True]
    if phase=='intent':
        assert writes==[] and not service._rows[id(lease)]['material'].write_entered
        value=service.apply(lease,token,**args)['fact']
    else:
        assert writes==[True];value=service.reconcile(lease)['fact']
    assert writes==[True] and service.reconcile(lease)['duplicate']
    assert store.audit()==store.replay() and value['candidate_write_fd_closed'] is True


@pytest.mark.parametrize('failure',['STOP','TTL'])
def test_actual_last_graph_boundary_blocks_write_and_retains_intent(engineering_runtime,monkeypatch,failure):
    owner,lease,service,args=stopped(engineering_runtime);token=engineering_runtime[2];utc,mono=engineering_runtime[-2:]
    from rlflow.hybrid_candidate_output_materials import CandidateOutputMaterial
    check=CandidateOutputMaterial.check_graph;trigger=[]
    def inject(material,*a,**kw):
        answer=check(material,*a,**kw)
        if material.fd is not None and not material.write_entered and not trigger:
            trigger.append(True)
            if failure=='STOP':(owner.store.root/'STOP').write_text('isolated last effect STOP')
            else:utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9
        return answer
    monkeypatch.setattr(CandidateOutputMaterial,'check_graph',inject)
    monkeypatch.setattr(os,'pwrite',lambda *a:pytest.fail('last graph boundary must deny effect'))
    with pytest.raises(Conflict,match='STOP|expired'):service.apply(lease,token,**args)
    material=service._rows[id(lease)]['material']
    assert trigger and not material.write_entered and (material.root/TARGET).read_bytes()==BEFORE
    assert len(owner.store.objects(SECTIONS[0]))==1 and owner.store.objects(SECTIONS[1])==[]
    if material.fd is not None:material.close_fd()
    assert owner.pool.snapshot()['occupied']==0


def test_actual_stale_request_not_poisoned_protected_facts_and_periodic_recovery(engineering_runtime):
    owner,lease,service,args=stopped(engineering_runtime);token=engineering_runtime[2];store=owner.store
    with pytest.raises(Conflict,match='stale'):service.apply(lease,token,**{**args,'expected_state_version':args['expected_state_version']-1})
    material=service._rows[id(lease)]['material']
    assert service._rows[id(lease)]['request'] is None and not material.write_entered
    value=service.apply(lease,token,**args)['fact'];key=result_key(value['request'])
    assert service._rows[id(lease)]['material'] is material
    with pytest.raises(PermissionError):store.transact(EVENTS[1],'forge',lambda s:None)
    with pytest.raises(PermissionError):store.transact_objects('OTHER','forge',[(SECTIONS[1],key)],lambda s:None)
    state=store.audit();lookup=lambda s,k:state.get(s,{}).get(k)
    bad=deepcopy(value);bad['controller']['fact_hash']='sha256:'+'0'*64
    with pytest.raises(Conflict,match='controller'):validate_links(SECTIONS[1],bad,lookup)
    prior=store.get(SECTIONS[0],value['request']['intent_key'])
    for deleted in (None,False,0,{},''):
        with pytest.raises(Conflict,match='closed'):
            validate_transition({'format':2,'put':[[SECTIONS[0],intent_key(prior['request']),prior]],'delete':deleted,'details':None},lookup,
                event_type=EVENTS[0],key=intent_key(prior['request']),object_id=digest(prior),producer='hybrid-core',
                version=prior['accepted_state_version'],registration=(prior['request']['project_id'],'fixture'))
    from rlflow.snapshot_maintenance import maintain
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(store.version(),))
    assert maintain(store,seconds=30) and store.recover()==state


def test_actual_fork_closes_inherited_core_write_fd_and_denies_cap(engineering_runtime):
    owner,lease,service,_=stopped(engineering_runtime)
    from rlflow.hybrid_candidate_output_materials import CandidateOutputMaterial
    material=CandidateOutputMaterial(owner,lease)
    with material.witness() as witness:
        material.begin_fd(witness[1]);fd=material.fd
        child=os.fork()
        if child==0:
            try:
                try:os.fstat(fd)
                except OSError:pass
                else:os._exit(10)
                try:material.check_hold()
                except PermissionError:pass
                else:os._exit(11)
                os._exit(0)
            except BaseException:os._exit(12)
        assert os.waitpid(child,0)[1]==0 and os.fstat(fd).st_ino==material.target_identity[1]
        material.close_fd();material.check_hold()
    assert (material.root/TARGET).read_bytes()==BEFORE


def test_actual_partial_write_unknown_never_repaired_or_promoted(engineering_runtime,monkeypatch):
    owner,lease,service,args=stopped(engineering_runtime);pwrite=os.pwrite;writes=[]
    def partial(fd,data,offset):writes.append(True);return pwrite(fd,data[:8],offset)
    with monkeypatch.context() as patch:
        patch.setattr(os,'pwrite',partial)
        with pytest.raises(Conflict,match='partial'):service.apply(lease,engineering_runtime[2],**args)
    monkeypatch.setattr(os,'pwrite',lambda *a:pytest.fail('UNKNOWN must not rewrite'))
    with pytest.raises(Conflict,match='content differs'):service.reconcile(lease)
    with pytest.raises(Conflict,match='reconcile'):service.apply(lease,engineering_runtime[2],**args)
    assert writes==[True] and owner.store.objects(SECTIONS[1])==[]
    material=service._rows[id(lease)]['material'];assert material.write_entered and material.closed


def test_original_engineering_grant_required_and_no_G_cannot_apply(engineering_runtime):
    owner,bundle,token,observation,claim,*_=engineering_runtime
    grant=owner.issue_engineering_patch_grant(bundle,token,observation)
    for bad in (None,replace(grant),json.loads(grant.raw)):
        with pytest.raises(PermissionError):owner.register(bundle,token,observation,claim,request_key='bad',scenario='engineering_patch',engineering_grant=bad)
    lease=owner.register(bundle,token,observation,claim,request_key='no_G',scenario='engineering_patch',engineering_grant=grant)
    owner.stop_to_terminal(lease);service=CandidateOutputService(owner)
    with pytest.raises(Conflict,match='result capability'):service.apply(lease,token,idempotency_key='repair',expected_state_version=owner.store.version())
    assert not owner._issued(lease)['spawn_entered'] and owner.pool.snapshot()['occupied']==0
    assert owner.store.objects(SECTIONS[0])==[]


def test_last_engineering_input_io_before_spawn_gate_cannot_launch_expired(engineering_runtime,monkeypatch):
    owner=engineering_runtime[0];grant,lease=engineering_lease(engineering_runtime)
    utc,mono=engineering_runtime[-2:];spawn=owner.sources._runtime_spawn;read=owner._engineering_input;armed=[];trigger=[]
    def launch(*args):
        armed.append(True)
        try:return spawn(*args)
        finally:armed.clear()
    def last_input(attempt):
        fd=read(attempt)
        if armed and not trigger:
            trigger.append(True);utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9
        return fd
    monkeypatch.setattr(owner.sources,'_runtime_spawn',launch);monkeypatch.setattr(owner,'_engineering_input',last_input)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('expired input IO must not launch'))
    with pytest.raises(Conflict,match='expired'):owner.start(lease)
    owner.request_stop(lease)
    attempt=owner._issued(lease)
    # HANDOFF_UNKNOWN is already durable. Missing PID must not be laundered
    # into NO_HANDOFF/FREE, even when this injected test observed no Popen.
    closed=owner.shutdown_safety()
    assert trigger and not attempt['spawn_entered'] and owner._engineering_grants[id(grant)]['fd'] is None
    assert closed['state']=='PHYSICAL_CLOSED_EXPOSURE_UNKNOWN' and not closed['pool_slots_freed']
    assert owner.pool.snapshot()['occupied']==1


def test_final_actual_candidate_output_strict_counter_and_cold_no_writer(engineering_runtime):
    owner,lease,service,args=stopped(engineering_runtime);token=engineering_runtime[2]
    with pytest.raises(Conflict,match='integer'):
        service.apply(lease,token,**{**args,'expected_state_version':float(args['expected_state_version'])})
    assert not service._rows
    value=service.apply(lease,token,**args)['fact'];key=result_key(value['request'])
    for path in (('accepted_state_version',),('request','expected_state_version'),('sources','source_version'),
            ('sources','contract_revision'),('controller','head_revision'),('controller_checked_monotonic_ns',)):
        bad=deepcopy(value);target=bad
        for name in path[:-1]:target=target[name]
        target[path[-1]]=float(target[path[-1]])
        if path==('request','expected_state_version'):bad['request_hash']=digest(bad['request'])
        with pytest.raises(Conflict,match='integer'):validate_record(SECTIONS[1],key,bad)
    from rlflow.store import Store
    cold=Store.attach_existing(owner.store.root,project_id=owner.workspace.project_id,data_mode='fixture')
    assert cold._hybrid_candidate_output_service is None and cold.audit()==owner.store.audit()
    with pytest.raises(PermissionError):cold.transact_objects('OTHER','forge',[(SECTIONS[1],key)],lambda s:None)
    assert cold.get(SECTIONS[1],key)==value


def test_original_pool_close_hash_cross_link_rejects_rehashed_history(engineering_runtime):
    owner,lease,service,args=stopped(engineering_runtime);store=owner.store
    result=service.apply(lease,engineering_runtime[2],**args)['fact']
    state=store.audit();lookup=lambda s,k:state.get(s,{}).get(k)
    section=SECTIONS[0];key=result['request']['intent_key'];intent=state[section][key]
    # All record shapes, claim/lease/terminal refs and original metadata remain
    # valid. Only the close witness points somewhere else.
    bad=deepcopy(intent);bad['pool_free']['payload']['close_witness_hash']='sha256:'+'f'*64
    validate_record(section,key,bad)
    with pytest.raises(Conflict,match='original Pool FREE'):validate_links(section,bad,lookup)
    bad_result=deepcopy(result);bad_result['pool_free']['payload']['close_witness_hash']='sha256:'+'f'*64
    with pytest.raises(Conflict,match='original Pool FREE'):validate_links(SECTIONS[1],bad_result,lookup)
    # Even consistent whole-event/object hashes cannot hide the missing
    # semantic linkage; bounded historical event decoding alone still passes.
    with store.connect() as db:
        projected=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,key)).fetchone()[0]
        original=db.execute('SELECT payload,payload_sha256,object_id FROM events WHERE idempotency_key=?',(key,)).fetchone()
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()[0]
        encoded=store._encode_value(db,bad);payload=json.loads(original['payload'])
        for row in payload['put']:
            if row[:2]==[section,key]:row[2]=encoded
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(encoded).decode(),section,key))
        # Explicit corruption of this private temporary fixture only. Restore
        # the identical append-only trigger before any reader checks the DB.
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=?,object_id=? WHERE idempotency_key=?',
            (canonical(payload).decode(),sha(payload),digest(bad),key))
        db.execute(trigger)
    try:
        with store.read_connection() as db:assert store._candidate_output_event(db,key)[0][2]==digest(bad)
        with pytest.raises(Conflict,match='original Pool FREE'):store.audit()
        # replay() is intentionally a compatibility projection read, not an
        # integrity check. The actual snapshot/recovery gates must reject it.
        with pytest.raises(Conflict,match='original Pool FREE'):store.snapshot()
        with pytest.raises(Conflict,match='original Pool FREE'):store.recover()
    finally:
        with store.connect() as db:
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(projected,section,key))
            db.execute('DROP TRIGGER no_update')
            db.execute('UPDATE events SET payload=?,payload_sha256=?,object_id=? WHERE idempotency_key=?',(*tuple(original),key))
            db.execute(trigger)
    assert store.audit()==state and store.replay()==state
    store.snapshot();assert store.recover()==state
