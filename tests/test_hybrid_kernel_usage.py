"""Real Linux reap observations and original authenticated fixed-unit consumer."""
from concurrent.futures import ThreadPoolExecutor
import copy
import os
import signal
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_kernel_usage import _KernelUsageCapture
from rlflow.hybrid_protocol import validate
from rlflow.hybrid_resource_telemetry import FixedUnitTelemetry
from tests.test_hybrid_host_execution import shared
from tests.test_hybrid_finite_host_app import application, path, start, stop, ORIGIN
from tests.test_execution_adapter import setup as native_setup


def child(code='sum(i*i for i in range(200000))'):
    process = subprocess.Popen([sys.executable, '-B', '-I', '-S', '-c', code],
        env={'LANG':'C.UTF-8'}, close_fds=True, start_new_session=True)
    capture = _KernelUsageCapture(process)
    assert capture.installed
    return process, capture


@pytest.mark.parametrize('poll', [False, True])
def test_actual_original_wait_and_poll_capture_once(poll):
    process, capture = child()
    reaps = []; wait4 = capture._kernel_wait
    def observed(pid, flags):
        value = wait4(pid, flags)
        if value[0]: reaps.append(value[0])
        return value
    capture._kernel_wait = observed
    try:
        if poll:
            deadline = time.monotonic()+5
            while process.poll() is None:
                assert time.monotonic()<deadline
                time.sleep(.002)
        assert process.wait(timeout=5)==0
        value = capture.snapshot()
        assert value['exit_code']==0 and value['source']=='LINUX_WAIT4'
        assert value['cpu_user_us']>=0 and value['cpu_system_us']>=0 and value['peak_rss_bytes']>0
        assert value['reaped_at'].endswith('Z') and reaps==[process.pid]
        value['cpu_user_us']=-1
        assert capture.snapshot()['cpu_user_us']>=0
        assert process.poll()==0 and process.wait(timeout=1)==0 and reaps==[process.pid]
    finally:
        if process.returncode is None: process.kill(); process.wait(timeout=5)


def test_concurrent_original_waits_keep_single_reap():
    process, capture = child('import time; time.sleep(.05)')
    reaps=[]; wait4=capture._kernel_wait
    def observed(pid,flags):
        value=wait4(pid,flags)
        if value[0]:reaps.append(value[0])
        return value
    capture._kernel_wait=observed
    try:
        with ThreadPoolExecutor(max_workers=3) as workers:
            results=list(workers.map(lambda _:process.wait(timeout=5),range(3)))
        assert results==[0,0,0] and reaps==[process.pid]
        assert capture.snapshot()['exit_code']==0
    finally:
        if process.returncode is None:process.kill();process.wait(timeout=5)


def test_real_SIGKILL_external_reap_and_observation_failure_remain_distinct(monkeypatch):
    process,capture=child('import time; time.sleep(5)')
    os.kill(process.pid,signal.SIGSTOP);os.kill(process.pid,signal.SIGKILL)
    assert process.wait(timeout=5)==-signal.SIGKILL
    assert capture.snapshot()['exit_code']==-signal.SIGKILL
    external,missing=child()
    assert os.waitpid(external.pid,0)[0]==external.pid
    assert external.poll()==0 and missing.snapshot() is None
    failed,unknown=child()
    with monkeypatch.context() as patch:
        patch.setattr('rlflow.hybrid_kernel_usage.utc',lambda:(_ for _ in ()).throw(ValueError('clock observation failed')))
        assert failed.wait(timeout=5)==0
    assert unknown.snapshot() is None and failed.returncode==0


def test_fork_refuses_before_inherited_wait_lock():
    process,capture=child('import time; time.sleep(.1)')
    read,write=os.pipe();process._waitpid_lock.acquire()
    fork=os.fork()
    if fork==0:
        os.close(read)
        signal.alarm(3)
        try:
            for call in (process.poll,lambda:process.wait(timeout=.1),capture.snapshot):
                try:call()
                except PermissionError:continue
                os._exit(2)
            os.write(write,b'refused');os._exit(0)
        except BaseException:os._exit(3)
    os.close(write)
    try:
        assert os.read(read,20)==b'refused'
        assert os.waitpid(fork,0)[1]==0
    finally:
        os.close(read);process._waitpid_lock.release()
        assert process.wait(timeout=5)==0
    assert capture.snapshot()['exit_code']==0


def test_authenticated_actual_results_publish_only_explicit_final_sample(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        for unit,service,observer in zip(units,services,observers):
            url=f'/api/v1/projects/{service.project_id}/telemetry'
            response=client.post(path(service)+'/commands',headers=headers,json=start(service))
            assert response.status_code==202,response.text
            attempt=unit._actual();row=unit.runtime.sources._issued(attempt['source'])
            capture=row['kernel_usage'];assert capture.snapshot()['exit_code']==0
            # Reading an older slot cannot upgrade it from the completed reap.
            assert client.get(url).json()['workers'][0]['final_usage'] is None
            version=unit.runtime.store.version()
            assert observer.sample()
            sample=client.get(url).json();validate('Telemetry',sample)
            final=sample['workers'][0]['final_usage']
            assert final==capture.snapshot() and final['scope']=='FIXED_PARTICIPANT_LIFETIME'
            assert sample['workers'][0]['process']['status']=='UNKNOWN'
            assert unit.runtime.store.version()==version
            with monkeypatch.context() as patch:
                def forbidden(*a,**k):pytest.fail('telemetry GET must not reap or execute')
                patch.setattr(row['producer'],'poll',forbidden)
                patch.setattr(row['producer'],'wait',forbidden)
                patch.setattr(observer,'sample',forbidden)
                assert client.get(url).json()['workers'][0]['final_usage']==final
            detached=observer.latest();detached['workers'][0]['final_usage']['exit_code']=42
            assert observer.latest()['workers'][0]['final_usage']==final
            with monkeypatch.context() as patch:
                issued=observer._slot[1]
                patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued+16)
                stale=observer.latest()
                assert stale['workers'][0]['process']['status']=='UNKNOWN'
                assert stale['workers'][0]['final_usage']==final
            # STOP does not erase historical final observations or invent a new sample.
            stopped=client.post(path(service)+'/commands',headers={**headers,'Idempotency-Key':'stop-final'},json=stop(service))
            assert stopped.status_code==202,stopped.text
            assert observer.latest()['workers'][0]['final_usage']==final
            retired=observer.latest()
            original=row['kernel_usage'];row['kernel_usage']=copy.copy(original)
            withdrawn=observer.latest()
            assert withdrawn['workers'][0]['final_usage'] is None
            assert withdrawn['sample_seq']==retired['sample_seq']+4
            assert withdrawn['observed_at']==retired['observed_at']
            assert withdrawn['source_state_version']==retired['source_state_version']
            assert not observer.sample()
            assert observer.latest()['workers'][0]['final_usage'] is None
            row['kernel_usage']=original
            assert observer.latest()['workers'][0]['final_usage'] is None
            assert observer.sample() and observer.latest()['workers'][0]['final_usage']==final
            known=observer.latest();hook=row['producer']._try_wait
            row['producer']._try_wait=capture._try
            withdrawn=observer.latest()
            assert withdrawn['workers'][0]['final_usage'] is None
            assert withdrawn['sample_seq']==known['sample_seq']+4
            row['producer']._try_wait=hook
            assert observer.latest()['workers'][0]['final_usage'] is None
            assert observer.sample() and observer.latest()['workers'][0]['final_usage']==final
            malformed=copy.deepcopy(sample);malformed['workers'][0]['process']['scope']='SUPERVISOR_PROCESS'
            with pytest.raises(ValueError):validate('Telemetry',malformed)
            print('actual_authenticated_final_kernel_usage',service.project_id,final,flush=True)
        assert units[0]._last['status']=='EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
        assert units[1]._last['status']=='MACHINE_ACCEPTED_PENDING_REVIEW'
        assert host.pool.snapshot()['occupied']==0


def test_actual_original_live_worker_hook_loss_cannot_block_HTTP_STOP(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    unit,service,observer=units[0],services[0],observers[0]
    entered=threading.Event();register=unit.runtime._register_release
    def waiting(attempt):
        row=unit.runtime.sources._issued(attempt['source']);capture=row['kernel_usage']
        assert row['producer'].poll() is None
        row['producer']._try_wait=capture._try  # Loss of one observer hook, not a new process.
        assert not capture._bound()
        entered.set();assert unit._cancelled.wait(3)
        return register(attempt)
    monkeypatch.setattr(unit.runtime,'_register_release',waiting)
    other_version=units[1].runtime.store.version()
    with TestClient(app,base_url=ORIGIN) as client,ThreadPoolExecutor(max_workers=1) as worker:
        client.cookies.set('rlflow_session',token)
        future=worker.submit(client.post,path(service)+'/commands',headers=headers,json=start(service))
        assert entered.wait(8)
        response=client.post(path(service)+'/commands',headers={**headers,'Idempotency-Key':'hook-loss-stop'},json=stop(service))
        assert response.status_code==202,response.text
        assert future.result(timeout=10).status_code==202
    attempt=unit._actual();row=unit.runtime.sources._issued(attempt['source'])
    assert row['producer'].poll() is not None and not attempt['release_entered']
    assert all(fd is None for fd in row['fds'].values())
    assert observer.latest()['workers'][0]['final_usage'] is None
    assert host.pool.snapshot()['occupied']==1 and units[1].runtime.store.version()==other_version
    print('actual_hook_loss_HTTP_STOP',dict(reaped=True,all_FDs_closed=True,G=False,final_usage='UNKNOWN',other_store_unchanged=True),flush=True)


def test_retired_read_uses_its_locked_revision_during_concurrent_sample(shared,monkeypatch):
    host,units=shared;observer=FixedUnitTelemetry(host,units[0].lease)
    assert observer.sample();value,issued,source=observer._slot
    observer._slot=(value,issued-16,source)
    entered=threading.Event();release=threading.Event();deepcopy=copy.deepcopy
    def paused(value):
        if threading.current_thread().name=='retired-resource-reader':
            entered.set();assert release.wait(3)
        return deepcopy(value)
    monkeypatch.setattr('rlflow.hybrid_resource_telemetry.copy.deepcopy',paused)
    result=[];reader=threading.Thread(target=lambda:result.append(observer.latest()),name='retired-resource-reader')
    reader.start();assert entered.wait(3)
    try:
        assert observer.sample()  # Resets shared retirement after old read releases its lock.
    finally:release.set();reader.join(5)
    assert not reader.is_alive() and len(result)==1
    assert all(metric['status']=='UNKNOWN' for metric in result[0]['host'].values())
    assert observer.latest()['host']['memory']['status']=='KNOWN'
