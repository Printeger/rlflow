"""Actual isolated owner SIGKILL; physical scope retirement is not FREE."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.store import Store
from rlflow.hybrid_reads import ReadBudget

WORKER=r'''
import json,sys,time
from pathlib import Path
from rlflow.isolated_local_cpu import isolated_session
from rlflow.hybrid_budget_ledger import reservation_key
spec={'purpose':'research','code':'import os,time\nprint("checkpoint-before-crash",flush=True)\np=os.fork()\nif not p:os.setsid()\nwhile True:time.sleep(1)',
    'inputs':{},'seconds':20,'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12},
    'acceptance':{'method':'EXACT_STDOUT_UTF8','stdout':'checkpoint-before-crash\n','stderr_empty':True}}
with isolated_session(Path(sys.argv[1]),spec,approved=True,confirmation_reader=lambda p,c:'APPROVE '+c['scope_hash']) as s:
    runtime=s['runtime'];lease=s['lease'];runtime.start(lease)
    row=runtime.sources._issued(runtime._issued(lease)['source'])
    print(json.dumps({'crash_ready':True,'unit':row['manager'].unit,'keeper':row['ready']['keeper'],
        'task':row['ready']['task'],'root':str(runtime.store.root),'epoch':runtime.plans.workspace.store_epoch,
        'reservation':reservation_key(s['reserve']),
        'application_root':str(runtime.pool.application_root),
        'descriptor_sha256':runtime.pool.descriptor_sha256,
        'descriptor_identity':runtime.pool.descriptor_identity}),flush=True)
    sys.stdin.readline()
'''


def unit_state(unit):
    result=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState','--property=MainPID','--property=LoadState'],
        capture_output=True,text=True,timeout=3)
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def test_owner_crash_retires_physical_service_without_forging_budget_terminal(tmp_path,monkeypatch):
    tmp_path.chmod(0o700)
    worker=subprocess.Popen([sys.executable,'-c',WORKER,str(tmp_path)],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},bufsize=0)
    held=[];ready=None;tail=b''
    try:
        end=time.monotonic()+30
        while ready is None:
            assert time.monotonic()<end,'actual worker ready deadline'
            if not select.select([worker.stdout],[],[],.1)[0]:continue
            raw=os.read(worker.stdout.fileno(),32768)
            assert raw,'worker failed before crash injection'
            tail+=raw;assert len(tail)<=65536
            while b'\n' in tail:
                line,tail=tail.split(b'\n',1)
                try:value=json.loads(line)
                except ValueError:continue
                if value.get('crash_ready'):ready=value
        children=Path(f"/proc/{ready['task']['pid']}/task/{ready['task']['pid']}/children")
        end=time.monotonic()+2
        while not children.read_text().strip() and time.monotonic()<end:time.sleep(.01)
        descendants=[int(pid) for pid in children.read_text().split()]
        assert descendants,'actual setsid descendant required for crash proof'
        # Original live kernel handles captured before killing only this
        # disposable worker. No reconstructed product STOP/controller grant.
        for pid in (ready['keeper']['pid'],ready['task']['pid'],*descendants):held.append(os.pidfd_open(pid))
        worker.send_signal(signal.SIGKILL);assert worker.wait(timeout=4)==-signal.SIGKILL
        end=time.monotonic()+7
        while time.monotonic()<end:
            state=unit_state(ready['unit'])
            if state.get('LoadState')=='not-found' and state.get('MainPID')=='0':break
            time.sleep(.05)
        assert state.get('ActiveState') in ('inactive','failed') and state.get('MainPID')=='0',state
        assert state.get('LoadState')=='not-found',state
        assert len(select.select(held,[],[],0)[0])==len(held)
        store=Store.attach_existing(ready['root'],project_id='isolated_local_cpu',data_mode='fixture')
        version=store.version();reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=ready['epoch'])
        history=reader.task(ready['reservation'],timeline=True)
        assert history['task']['recorded_budget_status']=='UNKNOWN'
        assert history['task']['recorded_phase'] in ('RELEASE_INTENT','STARTED_AS_OBSERVED')
        assert history['managed_terminal_proof'] is None and history['recorded_settled_usage'] is None
        assert not history['task']['controls_available'] and not history['task']['condition_evidence']
        assert store.version()==version
        recovered=reader.recover_task_evidence(ready['reservation'])
        evidence=recovered['task_evidence'];assert evidence is not None
        assert evidence['physical_scope_status']=='ORIGINAL_CONTROLLED_SCOPE_CLOSED'
        physical=evidence['physical_scope_proof'];assert physical is not None
        assert physical['original_processes_terminal'] and not physical['original_manager_job_recovered']
        assert physical['keeper']==ready['keeper'] and physical['signed_task_closed']==evidence['task_closed']
        assert physical['original_binding']['scope']['path'].endswith('/'+ready['unit'])
        result=evidence['configured_local_result'];assert result is not None
        assert result['outputs']['stdout']['text']=='checkpoint-before-crash\n'
        assert result['execution']['control_terminal_reason']=='CONTROL_EOF'
        assert result['machine_acceptance']['status']=='FAIL'
        assert not recovered['managed_terminal_recovered'] and not recovered['controls_available']
        assert not recovered['execution_replayed'] and not recovered['settlement_performed']
        assert store.version()==version and reader.task(ready['reservation'])['task']['recorded_budget_status']=='UNKNOWN'
        # A genuinely cold public CLI consumes the same original report, not
        # Python objects from the dead parent; not a new task execution.
        cli=subprocess.run([sys.executable,'-m','rlflow.isolated_local_cpu','history',
            '--root',ready['root'],'--store-epoch',ready['epoch'],'--reservation-id',ready['reservation'],
            '--recover-task-evidence'],capture_output=True,text=True,timeout=15)
        assert cli.returncode==0,cli.stderr
        assert json.loads(cli.stdout)==recovered
        # Same-inode output mutation cannot replace the trusted keeper seal.
        with reader.snapshot() as (db,meta):
            head=reader._head(db,ReadBudget(db,16*1024**2),
                ready['reservation'],meta['as_of_state_version'])[0]
            process=reader._point(db,ReadBudget(db,16*1024**2),
                head['fixture_runtime']['previous']['key'],meta['as_of_state_version'])
            assert process['request']['fixture_runtime']['phase']=='PROCESS_REGISTERED'
            (tmp_path/'crash-pre-g-process.json').write_text(json.dumps(process))
            (tmp_path/'crash-recovery-binding.json').write_text(json.dumps(head['fixture_runtime']))
        source=Path(head['fixture_runtime']['local_cpu_recovery_source']['path'])
        (tmp_path/'crash-v2-original-report.json').write_bytes((source/'task-report').read_bytes())
        output=source/'task-stdout';original=output.read_bytes()
        output.write_bytes(b'forged PASS\n')
        try:
            import pytest
            from rlflow.store import Conflict
            with pytest.raises(Conflict,match='output hash differs'):reader.recover_task_evidence(ready['reservation'])
        finally:output.write_bytes(original)
        # Both originals can be modified without changing inode: the report
        # signature must still reject forged hashes and a forged successful exit.
        report_path=source/'task-report';report_original=report_path.read_bytes()
        forged=json.loads(report_original)
        forged['outputs']['stdout']=__import__('hashlib').sha256(b'forged PASS\n').hexdigest()
        forged['task_closed']['stopped']['control_terminal_reason']='PRODUCER_EXIT'
        for item in forged['task_closed']['stopped']['reaped']:
            if item['pid']==forged['task_closed']['task']['pid']:item['status']=0
        output.write_bytes(b'forged PASS\n');report_path.write_text(json.dumps(forged)+'\n')
        try:
            with pytest.raises(Conflict,match='signature differs'):reader.recover_task_evidence(ready['reservation'])
        finally:output.write_bytes(original);report_path.write_bytes(report_original)
        assert reader.recover_task_evidence(ready['reservation'])==recovered
        # Protected startup uses the actual before-crash installation pins,
        # not any reconstructed claim/source/manager capability. Only read.
        pool=HostPoolOwner.trusted_attach(ready['application_root'],ready['descriptor_sha256'],ready['descriptor_identity'])
        try:
            before=pool.snapshot();assert before['occupied']==1
            assert not pool._claims and not pool._claim_slots
            assert pool.snapshot()==before and store.version()==version
            (tmp_path/'crash-pool.json').write_text(json.dumps(before))
            membership=pool.join_registered('isolated_local_cpu')
            claim_key=before['heads'][0]['claim_key']
            import copy,fcntl
            copied=copy.copy(pool)
            class DerivedPool(HostPoolOwner):pass
            derived=copy.copy(pool);derived.__class__=DerivedPool
            for other in (copied,derived):
                with pytest.raises(PermissionError,match='registered physical retirement'):
                    other.retire_local_cpu(membership,claim_key=claim_key,
                        reservation_id=ready['reservation'],expected_version=before['version'])
            with pytest.raises(Conflict,match='stale physical retirement'):
                pool.retire_local_cpu(membership,claim_key=claim_key,
                    reservation_id=ready['reservation'],expected_version=before['version']-1)
            # Protected reconcile rereads original signed evidence, not the
            # public DTO above. A forged report cannot retire an occupied slot.
            report_path.write_text(json.dumps(forged)+'\n')
            try:
                with pytest.raises(Conflict,match='signature differs'):
                    pool.retire_local_cpu(membership,claim_key=claim_key,
                        reservation_id=ready['reservation'],expected_version=before['version'])
                assert pool.snapshot()==before and store.version()==version
            finally:report_path.write_bytes(report_original)
            lock_fd=os.open(pool.root/'slot0',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
            try:
                fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with pytest.raises(BlockingIOError):
                    pool.retire_local_cpu(membership,claim_key=claim_key,
                        reservation_id=ready['reservation'],expected_version=before['version'])
                assert pool.snapshot()==before and store.version()==version
            finally:os.close(lock_fd)
            original_close=os.close;failed_close=[]
            def close_fault(fd):
                retained=pool._slots.get(0)
                if retained is not None and not retained.closed and fd==retained.fds[0]:
                    failed_close.append(fd);raise OSError('injected retirement slot close failure')
                return original_close(fd)
            with monkeypatch.context() as patch:
                patch.setattr(os,'close',close_fault)
                with pytest.raises(Conflict,match='slot cleanup uncertain'):
                    pool.retire_local_cpu(membership,claim_key=claim_key,
                        reservation_id=ready['reservation'],expected_version=before['version'])
            retained=pool._slots[0]
            assert len(failed_close)==1 and retained.fds[0]==failed_close[0] and retained.fds[1] is None
            assert not retained.closed and pool.snapshot()==before and store.version()==version
            # Explicit cleanup of the retained exact new temporary object,
            # not an automatic retry or recreation of the dead owner's claim.
            retained.close()
            import sqlite3
            original_connect=sqlite3.connect
            for commit_phase in ('before','after'):
                injected=[]
                class CommitFault(sqlite3.Connection):
                    def commit(self):
                        if not injected:
                            injected.append(commit_phase)
                            if commit_phase=='after':super().commit()
                            raise OSError('injected physical retirement commit lost return '+commit_phase)
                        return super().commit()
                def connect(path,*args,**kwargs):
                    if str(path).startswith((pool.root/'pool.db').as_uri()):kwargs['factory']=CommitFault
                    return original_connect(path,*args,**kwargs)
                with monkeypatch.context() as patch:
                    patch.setattr(sqlite3,'connect',connect)
                    with pytest.raises(OSError,match='commit lost return'):
                        pool.retire_local_cpu(membership,claim_key=claim_key,
                            reservation_id=ready['reservation'],expected_version=before['version'])
                assert injected==[commit_phase] and store.version()==version
                observed=pool.snapshot()
                assert observed['occupied']==(1 if commit_phase=='before' else 0)
                assert observed['version']==before['version']+(commit_phase=='after')
            retired=pool.retire_local_cpu(membership,claim_key=claim_key,
                reservation_id=ready['reservation'],expected_version=before['version'])
            after=pool.snapshot();assert after['occupied']==0
            assert after['heads'][0]['state']=='LOCAL_CPU_PHYSICALLY_RETIRED'
            assert pool.retire_local_cpu(membership,claim_key=claim_key,
                reservation_id=ready['reservation'],expected_version=before['version'])==retired
            assert pool.snapshot()==after and store.version()==version
            assert reader.task(ready['reservation'])['task']['recorded_budget_status']=='UNKNOWN'
            (tmp_path/'crash-retirement.json').write_text(json.dumps(retired))
            (tmp_path/'crash-retired-pool.json').write_text(json.dumps(after))
        finally:pool.shutdown()
        # Another cold protected owner audits the retirement source and reuses
        # the actual slot, without recreating the old execution or settling it.
        moved_report=report_path.with_name('retired-report-held-by-test')
        report_path.rename(moved_report)
        pool=HostPoolOwner.trusted_attach(ready['application_root'],ready['descriptor_sha256'],ready['descriptor_identity'])
        try:
            assert pool.snapshot()==after
            membership=pool.join_registered('isolated_local_cpu')
            new=pool.claim(membership,expected_version=after['version'],request_key='new_after_physical_retirement')
            assert json.loads(new.raw)['slot']==0 and pool.snapshot()['occupied']==1
            new_before=pool.snapshot()
            assert pool.retire_local_cpu(membership,claim_key=claim_key,
                reservation_id=ready['reservation'],expected_version=before['version'])==retired
            assert pool.snapshot()==new_before and pool.check(new)['claim_id']==new.id
            closing=pool.request_close_no_handoff(new,expected_version=new_before['version'])
            witness=pool.close_original(closing)
            pool.complete_close(witness,expected_version=pool.snapshot()['version'])
            assert pool.snapshot()['occupied']==0 and store.version()==version
            assert reader.task(ready['reservation'])['task']['recorded_budget_status']=='UNKNOWN'
            (tmp_path/'crash-reused-pool.json').write_text(json.dumps(pool.snapshot()))
        finally:
            pool.shutdown();moved_report.rename(report_path)
        (tmp_path/'crash-history.json').write_text(json.dumps(history))
        (tmp_path/'crash-recovery.json').write_text(json.dumps(recovered))
        (tmp_path/'crash-state.json').write_text(json.dumps(state))
    finally:
        if worker.poll() is None:
            worker.stdin.close();worker.wait(timeout=30)
        # Existing finite service RuntimeMaxSec is the fixture cleanup fallback,
        # never a cold STOP by unit name or a fake business FREE/settlement.
        if ready is not None:
            end=time.monotonic()+28
            while time.monotonic()<end:
                if unit_state(ready['unit']).get('ActiveState') in ('inactive','failed'):break
                time.sleep(.1)
        for fd in held:os.close(fd)
        worker.stdout.close();worker.stderr.close()
        if not worker.stdin.closed:worker.stdin.close()
