"""Actual local processes and original owners; synthetic account, zero model exec."""
import json
import os
import select
import signal
import subprocess
import threading

import pytest

from rlflow.store import Conflict
from tests.test_hybrid_native_account_cache import account_original,original,native_setup
from tests.test_hybrid_native_model_launch import register,ACTUAL_POPEN


def test_total_entry_intercepted_g_latches_and_cleans_original_owner(account_original,monkeypatch):
    owner,lease,home=register(account_original)
    attempt=owner._issued(lease);row=owner.sources._issued(attempt['source']);writes=[]
    owner.prepare_current_account_cache(lease)
    launch=owner.prepare_native_launch(lease)
    class NoG:
        def __init__(self,pipe):self.pipe=pipe
        def fileno(self):return self.pipe.fileno()
        @property
        def closed(self):return self.pipe.closed
        def close(self):return self.pipe.close()
        def write(self,data):
            assert data==b'G';writes.append(data)
            raise PermissionError('TEST total A G intercepted')
        def flush(self):pytest.fail('no intercepted G flush')
    def gate_only(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        child=ACTUAL_POPEN(argv,*args,**kwargs);child.stdin=NoG(child.stdin)
        return child
    monkeypatch.setattr(subprocess,'Popen',gate_only)
    def no_issuer(*args):pytest.fail('failed Engineer cannot dispatch Reviewer')
    with pytest.raises(PermissionError,match='TEST total A G intercepted'):
        owner.run_workflow_engineering(lease,launch=launch,launch_issuer=no_issuer)
    assert writes==[b'G'] and owner._workflow_engineering_sequence['phase']=='FAILED'
    assert owner._workflow_engineering_completed is None
    assert not owner._live and not owner.sources._live
    assert row['producer'].poll() is not None and row['producer'].stdin.closed
    assert all(fd is None for fd in row['fds'].values())
    assert owner.sources._account_caches[id(attempt['source'])].descriptors()==()
    assert owner.pool.snapshot()['occupied']==0 and owner._current(attempt)['status']=='UNKNOWN'
    assert (home/'auth.json').read_bytes()==b'{"synthetic":"NOT_A_TOKEN"}'
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    with pytest.raises(Conflict,match='already latched'):
        owner.run_workflow_engineering(lease,launch=launch,launch_issuer=no_issuer)
    assert writes==[b'G'] and versions==(owner.store.version(),owner.pool.snapshot()['version'])
    # Cleanup by the exception handler is not the root STOP's original ACK.
    result=owner.stop_workflow_engineering()
    assert result['status']=='UNKNOWN' and not result['normal_stop_confirmed']
    assert not result['new_work_enabled'] and not result['goal_completed']
    assert owner.store.audit()==owner.store.replay()


def test_original_preentry_stop_ack_repeats_without_new_effects(account_original,monkeypatch):
    owner,lease,_=register(account_original)
    attempt=owner._issued(lease)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('STOP cannot start model'))
    result=owner.stop_workflow_engineering()
    assert result['normal_stop_confirmed'] and not owner._live and not owner.sources._live
    assert owner.pool.snapshot()['occupied']==0 and owner._current(attempt)['status']=='SETTLED'
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    assert owner.stop_workflow_engineering()==result
    assert versions==(owner.store.version(),owner.pool.snapshot()['version'])
    assert owner.store.audit()==owner.store.replay()


def test_fork_stop_refuses_before_inherited_locked_admission_or_latch(original):
    owner,*_=original
    # Exercise the retained root branch, not only pre-entry STOP.
    owner._workflow_engineering_root=(owner,None,owner.budget,owner.pool,
        owner.membership,owner._workflow_engineering_stop)
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    held=threading.Event();release=threading.Event()
    def hold():
        with owner._workflow_cpu_admission_lock:
            held.set();assert release.wait(10)
    thread=threading.Thread(target=hold);thread.start();assert held.wait(5)
    read_fd,write_fd=os.pipe();child=None
    try:
        child=os.fork()
        if child==0:
            os.close(read_fd)
            try:
                owner.stop_workflow_engineering();error='NO_REFUSAL'
            except BaseException as exc:error=type(exc).__name__
            os.write(write_fd,json.dumps({'error':error,
                'latched':owner._workflow_engineering_stop.is_set(),
                'ack':owner._workflow_engineering_stop_ack is not None}).encode())
            os._exit(0)
        os.close(write_fd);write_fd=None
        assert select.select([read_fd],[],[],5)[0], 'fork STOP waited on inherited lock'
        result=json.loads(os.read(read_fd,4096))
        assert os.waitpid(child,0)[1]==0;child=None
        assert result=={'error':'PermissionError','latched':False,'ack':False}
    finally:
        if child is not None and child>0:
            os.kill(child,signal.SIGKILL);os.waitpid(child,0)
        os.close(read_fd)
        if write_fd is not None:os.close(write_fd)
        release.set();thread.join(5)
    assert not thread.is_alive() and not owner._workflow_engineering_stop.is_set()
    assert owner._live and owner.sources._live and owner._workflow_engineering_stop_ack is None
    assert versions==(owner.store.version(),owner.pool.snapshot()['version'])
