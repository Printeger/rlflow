"""Actual cold kernel thread-group gate; no execution or FREE capability."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import pytest

from rlflow.hybrid_local_cpu_recovery import _original_dead
from rlflow.store import Conflict


def test_zombie_leader_with_live_thread_never_proves_owner_terminal(tmp_path):
    script='''
import ctypes,json,sys,threading,os
from rlflow.jobs import identity
ready=threading.Event()
def alive():
 ready.set()
 sys.stdin.readline()
 os._exit(0)
threading.Thread(target=alive).start()
ready.wait()
print(json.dumps(identity(os.getpid())),flush=True)
ctypes.CDLL(None).pthread_exit(None)
'''
    worker=subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    held=None
    try:
        assert select.select([worker.stdout],[],[],5)[0]
        original=json.loads(worker.stdout.readline());held=os.pidfd_open(worker.pid)
        end=time.monotonic()+5
        while True:
            state=Path(f'/proc/{worker.pid}/stat').read_text().rsplit(')',1)[1].split()[0]
            if state=='Z':break
            assert time.monotonic()<end
            time.sleep(.01)
        assert not select.select([held],[],[],0)[0]
        descriptors=set(os.listdir('/proc/self/fd'))
        assert not _original_dead(original)
        assert set(os.listdir('/proc/self/fd'))==descriptors
        worker.stdin.write('finish\n');worker.stdin.flush()
        assert select.select([held],[],[],5)[0] and worker.wait(timeout=3)==0
        assert _original_dead(original)
        (tmp_path/'zombie-leader.json').write_text(json.dumps({'original':original,
            'leader_state_before':'Z','whole_group_terminal_before':False,'whole_group_terminal_after':True}))
    finally:
        if worker.poll() is None:worker.kill();worker.wait(timeout=5)
        for stream in (worker.stdin,worker.stdout,worker.stderr):stream.close()
        if held is not None:os.close(held)


@pytest.mark.parametrize('source',['process-stat','pidfd'])
@pytest.mark.parametrize('fault',['fstat','close'])
def test_kernel_cleanup_fault_retains_original_fd_and_closes_independent_source(monkeypatch,source,fault):
    from rlflow.jobs import identity
    original_close=os.close;original_fstat=os.fstat;affected={};closed=[]
    original_open=os.open;original_pidfd=os.pidfd_open
    def capture(fd,label):
        info=original_fstat(fd)
        affected[label]=(fd,(info.st_dev,info.st_ino));return fd
    monkeypatch.setattr(os,'open',lambda *args,**kwargs:capture(original_open(*args,**kwargs),'process-stat'))
    monkeypatch.setattr(os,'pidfd_open',lambda *args,**kwargs:capture(original_pidfd(*args,**kwargs),'pidfd'))
    def fstat(fd):
        if fault=='fstat' and affected.get(source,(None,))[0]==fd:
            affected.setdefault('seen',0);affected['seen']+=1
            if affected['seen']>1:raise OSError(5,'injected cleanup fstat failed')
        return original_fstat(fd)
    def close(fd):
        if fault=='close' and affected.get(source,(None,))[0]==fd:raise OSError(5,'injected cleanup close failed')
        original_close(fd);closed.append(fd)
    monkeypatch.setattr(os,'fstat',fstat);monkeypatch.setattr(os,'close',close)
    with pytest.raises(Conflict,match='cleanup failed') as caught:_original_dead(identity(os.getpid()))
    retained=caught.value.original_recovery_kernel_fds
    assert retained==[{'fd':affected[source][0],'identity':affected[source][1],'source':source}]
    if source=='process-stat':assert affected['pidfd'][0] in closed
    else:assert affected['process-stat'][0] in closed
    fd,expected=affected[source];info=original_fstat(fd);assert (info.st_dev,info.st_ino)==expected
    original_close(fd)  # Exact retained ORIGINAL test descriptor only.


@pytest.mark.parametrize('source',['process-stat','pidfd'])
def test_foreign_kernel_fd_is_retained_never_closed(monkeypatch,source):
    import rlflow.hybrid_local_cpu_recovery as recovery
    from rlflow.jobs import identity
    null=os.open('/dev/null',os.O_RDONLY);original=recovery._close_kernel_source
    changed=[];independent=[]
    def swapped(fd,expected,label):
        if label==source:
            os.dup2(null,fd);changed.append(fd)
        else:independent.append(label)
        return original(fd,expected,label)
    monkeypatch.setattr(recovery,'_close_kernel_source',swapped)
    try:
        with pytest.raises(Conflict,match='cleanup failed') as caught:_original_dead(identity(os.getpid()))
        assert changed and independent==['pidfd' if source=='process-stat' else 'process-stat']
        assert caught.value.original_recovery_kernel_fds[0]['fd']==changed[0]
        expected=os.fstat(null);actual=os.fstat(changed[0])
        assert (actual.st_dev,actual.st_ino)==(expected.st_dev,expected.st_ino)
    finally:
        for fd in changed:os.close(fd)  # Exact test-owned replacement only, not product adoption.
        os.close(null)
