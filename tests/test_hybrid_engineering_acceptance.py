"""Actual original candidate → readonly AST machine disposition, not Reviewer."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import os
import json
import pytest
from rlflow.hybrid_engineering_cold_verifier import derive,verify,implementation_hash
from rlflow.hybrid_engineering_patch import BEFORE,AFTER
from rlflow.hybrid_candidate_output import SECTIONS,result_key,validate_record,validate_links
from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
from rlflow.hybrid_goals import digest
from rlflow.store import Store,Conflict,canonical,sha
from tests.test_hybrid_engineering_output import engineering_runtime,stopped
from tests.test_execution_adapter import setup as native_setup


def test_actual_readonly_machine_acceptance_21_cases_original_bytes_no_rerun_and_cold_view(engineering_runtime,monkeypatch):
    writes=[];pwrite=os.pwrite
    def original_write(fd,data,offset):writes.append((data,offset));return pwrite(fd,data,offset)
    monkeypatch.setattr(os,'pwrite',original_write)
    owner,lease,service,args=stopped(engineering_runtime)
    original=service.apply(lease,engineering_runtime[2],**args)['fact'];key=result_key(original['request'])
    version=owner.store.version();engineering_runtime[6][0]+=timedelta(seconds=1);engineering_runtime[7][0]+=10**9
    request={'output_key':key,'idempotency_key':'accept_original','expected_state_version':version}
    with monkeypatch.context() as patch:
        for obj,name in ((owner,'start'),(owner,'run_engineering_patch'),(owner,'collect_engineering_patch'),(service,'apply'),(os,'pwrite')):
            patch.setattr(obj,name,lambda *a,**k:pytest.fail('acceptance cannot rewrite/rerun worker'))
        accepted=service.accept_machine(lease,**request)
        assert service.accept_machine(lease,**request)['duplicate']
    value=accepted['fact'];machine=value['machine_verification'];ak=result_key(value['request'])
    assert not accepted['duplicate'] and accepted['execution_authority']=='NONE'
    assert machine['status']=='MACHINE_ACCEPTED_PENDING_REVIEW' and machine['derived']['passed_cases']==21
    assert len(machine['derived']['actual_tests'])==21 and machine['condition_coverage']==[]
    assert machine['independent_review_status']=='NOT_PERFORMED' and not machine['goal_completed']
    assert value['sources']['evaluated_at']==original['sources']['evaluated_at'] and value['controller']==original['controller']
    assert owner.store.get(SECTIONS[1],key)==original and writes==[(AFTER,0)]
    with pytest.raises(PermissionError):service.accept_machine(replace(lease),**request)
    with pytest.raises(Conflict,match='request changed'):service.accept_machine(lease,**{**request,'idempotency_key':'other'})
    with pytest.raises(Conflict,match='plain original'):service.accept_machine(lease,**{**request,'output_key':ak})
    state=owner.store.audit();assert state==owner.store.replay();owner.store.snapshot();assert owner.store.recover()==state
    cold=Store.attach_existing(owner.store.root,project_id=owner.workspace.project_id,data_mode='fixture')
    reader=CandidateOutputReader(cold,owner.plans.registry,project_id=owner.workspace.project_id,store_epoch=owner.workspace.store_epoch)
    assert len(reader.outputs()['items'])==1
    assert reader.output_detail(key)['candidate']['machine_acceptance']['derived']['passed_cases']==21
    owner.shutdown();owner.pool.shutdown()
    assert reader.output_detail(key)['candidate']['machine_acceptance']['status']=='MACHINE_ACCEPTED_PENDING_REVIEW'
    assert owner.store.version()==version+1


def test_fixed_raw_AST_rejects_code_and_canonical_machine_corruption():
    machine=verify(AFTER,implementation=implementation_hash())
    assert derive(AFTER)['passed_cases']==21
    for raw in (BEFORE,AFTER+b'print(42)\n',AFTER+b'import os\n',b'def add(a,b=0):\n return a+b\n',b'def add(a,b):\n return sum((a,b))\n',b'def add(a,b):\n return b+a\n'):
        with pytest.raises(Conflict):derive(raw)
    from rlflow.hybrid_engineering_cold_verifier import validate
    for field in ('verifier_version','status','independent_review_status'):
        bad=deepcopy(machine);bad[field]='invented'
        with pytest.raises(Conflict):validate(bad)
    for path in (('derived','passed_cases'),('derived','actual_tests',0,'actual')):
        bad=deepcopy(machine);target=bad
        for name in path[:-1]:target=target[name]
        target[path[-1]]=float(target[path[-1]])
        with pytest.raises(Conflict):validate(bad)


def test_expired_audit_lost_commit_original_receipt_corrupt_history_and_periodic_snapshot(engineering_runtime,monkeypatch):
    from rlflow import hybrid_engineering_cold_verifier as verifier
    from rlflow.hybrid_candidate_output import event_inputs
    from rlflow.snapshot_maintenance import maintain
    owner,lease,service,args=stopped(engineering_runtime);store=owner.store
    original=service.apply(lease,engineering_runtime[2],**args)['fact'];key=result_key(original['request'])
    version=store.version();engineering_runtime[6][0]+=timedelta(seconds=120);engineering_runtime[7][0]+=120*10**9
    request={'output_key':key,'idempotency_key':'expired_original_audit','expected_state_version':version}
    with monkeypatch.context() as patch:
        patch.setattr(verifier,'implementation_hash',lambda:'sha256:'+'e'*64)
        with pytest.raises(Conflict,match='verifier changed'):service.accept_machine(lease,**request)
    assert store.version()==version
    connect=store.connect
    class LostReturn:
        def __init__(self,db):self.db=db
        def __getattr__(self,n):return getattr(self.db,n)
        def __enter__(self):return self
        def __exit__(self,*args):return self.db.__exit__(*args)
        def commit(self):self.db.commit();raise OSError('actual machine acceptance COMMIT lost receipt')
    with monkeypatch.context() as patch:
        patch.setattr(store,'connect',lambda:LostReturn(connect()))
        with pytest.raises(OSError,match='lost receipt'):service.accept_machine(lease,**request)
    accepted=service.accept_machine(lease,**request);value=accepted['fact'];ak=result_key(value['request'])
    assert accepted['duplicate'] and store.version()==version+1
    assert value['sources']['evaluated_at']==original['sources']['evaluated_at']
    assert value['recorded_at']>value['sources']['expires_at'] and not value['goal_completed']
    state=store.audit();lookup=lambda s,k:state.get(s,{}).get(k)
    bad=deepcopy(value);bad['request']['prior_output_hash']='sha256:'+'f'*64;bad['request_hash']=digest(bad['request'])
    validate_record(SECTIONS[1],ak,bad)
    with pytest.raises(Conflict,match='original output linkage'):validate_links(SECTIONS[1],bad,lookup)
    with store.connect() as db:
        projected=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(SECTIONS[1],ak)).fetchone()[0]
        event=db.execute('SELECT payload,payload_sha256,object_id,input_versions FROM events WHERE idempotency_key=?',(ak,)).fetchone()
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='no_update'").fetchone()[0]
        encoded=store._encode_value(db,bad);payload=json.loads(event['payload'])
        for row in payload['put']:
            if row[:2]==[SECTIONS[1],ak]:row[2]=encoded
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(encoded).decode(),SECTIONS[1],ak))
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=?,object_id=?,input_versions=? WHERE idempotency_key=?',
            (canonical(payload).decode(),sha(payload),digest(bad),canonical(event_inputs(bad)).decode(),ak))
        db.execute(trigger)
    try:
        with store.read_connection() as db:assert store._candidate_output_event(db,ak)[0][2]==digest(bad)
        for operation in (store.audit,store.snapshot,store.recover):
            with pytest.raises(Conflict,match='original output linkage'):operation()
    finally:
        with store.connect() as db:
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(projected,SECTIONS[1],ak))
            db.execute('DROP TRIGGER no_update')
            db.execute('UPDATE events SET payload=?,payload_sha256=?,object_id=?,input_versions=? WHERE idempotency_key=?',(*tuple(event),ak))
            db.execute(trigger)
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(store.version(),))
    assert maintain(store,seconds=30)
    with monkeypatch.context() as patch:
        patch.setattr(verifier,'implementation_hash',lambda:pytest.fail('history cannot inspect current implementation'))
        assert store.audit()==state and store.recover()==state
    assert store.get(SECTIONS[1],key)==original and store.version()==version+1
