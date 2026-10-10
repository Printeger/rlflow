"""Real installed native, original SDK and physical STOP; no model provider."""
import copy
import errno
import http.server
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from contextlib import closing

import pytest

from rlflow.isolated_native_diagnostic import isolated_session
from rlflow.hybrid_native_diagnostic import NativeDiagnosticGrant
from rlflow.store import Conflict,canonical


@pytest.fixture
def diagnostic(tmp_path):
    tmp_path.chmod(0o700)
    # Explicit synthetic fixture scope confirmation, NOT real human review.
    with isolated_session(tmp_path,approved=True,
            confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']) as session:
        yield session


def source_of(session):
    runtime=session['runtime'];attempt=runtime._issued(session['lease'])
    return runtime,attempt,runtime.sources._issued(attempt['source'])


def inflight(session):
    runtime,attempt,source=source_of(session);runtime.start(session['lease'])
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        value=runtime.poll(session['lease'])
        if source['received'].is_set() and value['phase']=='STARTED_AS_OBSERVED':return value
        if source['producer'].poll() is not None:pytest.fail('native exited before local inflight STOP')
        time.sleep(.01)
    pytest.fail('actual native inflight diagnostic deadline exceeded')


def test_original_native_inflight_stop_sources_fork_and_readback(diagnostic):
    runtime,attempt,source=source_of(diagnostic)
    value=inflight(diagnostic)
    assert runtime.pool.snapshot()['occupied']==1 and source['receiver_requests']==1
    assert value['source']['usage']['input_tokens'] is None
    assert value['source']['usage']['output_tokens'] is None and not value['source']['usage']['complete']
    assert value['actual_cost_status']=='UNKNOWN' and not value['model_access_verified']
    with pytest.raises(PermissionError):copy.copy(runtime.sources).poll(attempt['source'])
    with pytest.raises(PermissionError):copy.copy(runtime).start(diagnostic['lease'])
    with pytest.raises(PermissionError):diagnostic['adapter'].start(None)
    with pytest.raises(PermissionError):diagnostic['plans'].start(None)
    original_fds=[fd for fd in source['fds'].values() if fd is not None]
    original_fds.extend([source['server'].socket.fileno(),source['accepted'][0].fileno(),source['producer'].stdin.fileno()])
    read,write=os.pipe();pid=os.fork()
    if pid==0:
        os.close(read);valid=True
        try:
            try:runtime.sources.poll(attempt['source']);valid=False
            except PermissionError:pass
            for fd in original_fds:
                try:os.fstat(fd);valid=False
                except OSError:pass
            os.write(write,b'1' if valid else b'0')
        finally:os._exit(0)
    os.close(write)
    assert os.read(read,1)==b'1';os.close(read);assert os.waitpid(pid,0)[1]==0
    for fd in original_fds:os.fstat(fd)  # Child close did not shutdown parent.
    stopped=runtime.stop_to_terminal(diagnostic['lease'])
    assert stopped['scope']=='FIXED_NATIVE_SINGLE_TGID'
    assert source['producer'].poll() is not None and source['producer'].stdin.closed
    assert all(fd is None for fd in source['fds'].values()) and source['server'] is None
    assert not source['server_thread'].is_alive() and runtime.pool.snapshot()['occupied']==0
    assert runtime._current(attempt)['status']=='SETTLED'
    before=(runtime.store.version(),runtime.pool.snapshot()['version'])
    assert runtime.stop_to_terminal(diagnostic['lease'])==stopped
    assert before==(runtime.store.version(),runtime.pool.snapshot()['version'])
    report=diagnostic['reader'].task(diagnostic['reservation_id'],timeline=True)
    assert report['task']['kind']=='LOCAL_NATIVE_DIAGNOSTIC'
    assert report['task']['recorded_phase']=='FIXTURE_SCOPE_STOPPED'
    assert report['task']['current_execution_status']=='UNKNOWN' and report['task']['usage_status']=='NOT_PROVIDED'


def test_same_inode_config_and_mutable_row_laundering_denied_before_handoff(diagnostic):
    runtime,attempt,source=source_of(diagnostic)
    original=source['config_raw'];forged=json.loads(original)
    forged['env']['OPENAI_API_KEY']='forbidden-local-sentinel'
    forged['home']=str(source['path'].parent);source['config_raw']=canonical(forged)
    fd=os.open(source['path']/'launch.json',os.O_WRONLY|os.O_NOFOLLOW)
    try:os.ftruncate(fd,0);os.write(fd,source['config_raw'])
    finally:os.close(fd)
    before=(runtime.store.version(),runtime.pool.snapshot()['version'])
    with pytest.raises(Conflict,match='immutable'):runtime.start(diagnostic['lease'])
    assert not attempt['spawn_entered'] and not attempt['release_entered'] and source['producer'] is None
    assert source['receiver_requests']==0 and before==(runtime.store.version(),runtime.pool.snapshot()['version'])
    runtime.stop_to_terminal(diagnostic['lease'])
    assert not attempt['terminal']['new_process_creation_denied']
    assert attempt['terminal']['participant_proof']=='PRE_EXEC_FIXED_GATE_NO_RELEASE'


def test_failed_durable_stop_physically_reaps_but_keeps_exposure(diagnostic,monkeypatch):
    runtime,attempt,source=source_of(diagnostic);inflight(diagnostic)
    original=runtime._write_phase
    def failed(row,phase,**kwargs):
        if phase=='STOP_REQUESTED':raise OSError(errno.ENOSPC,'injected original STOP writer failure')
        return original(row,phase,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(runtime,'_write_phase',failed)
        with pytest.raises(OSError,match='STOP writer'):runtime.stop_to_terminal(diagnostic['lease'])
        assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
        assert source['server'] is None and not source['server_thread'].is_alive()
        assert runtime.pool.snapshot()['occupied']==1 and runtime._current(attempt)['status']=='UNKNOWN'
        assert attempt['terminal'] is None and attempt['physical_safety_freeze'] and attempt['source_stop_latched']
        with pytest.raises(Conflict):runtime.start(diagnostic['lease'])
    # Original explicit safety retirement, never terminal/FREE/retry start.
    result=runtime.shutdown_safety()
    assert not result['pool_slots_freed'] and not result['refund_enabled']
    assert runtime.pool.snapshot()['occupied']==1


def test_lost_original_popen_return_never_adopts_or_frees(diagnostic,monkeypatch):
    runtime,attempt,source=source_of(diagnostic);popen=subprocess.Popen;returned=[]
    def lost(argv,**kwargs):
        process=popen(argv,**kwargs);returned.append(process)
        raise OSError(errno.EIO,'injected lost original Popen return')
    with monkeypatch.context() as patch:
        patch.setattr(subprocess,'Popen',lost)
        with pytest.raises(OSError,match='Popen return'):runtime.start(diagnostic['lease'])
    assert len(returned)==1 and source['producer'] is None and not attempt['release_entered']
    with pytest.raises(Conflict,match='unknown'):runtime.stop_to_terminal(diagnostic['lease'])
    assert source['receiver_requests']==0 and runtime.pool.snapshot()['occupied']==1
    assert runtime._current(attempt)['status']=='UNKNOWN' and attempt['terminal'] is None
    # Test's independent retained Popen closes its original gate pipe. The
    # product MUST NOT adopt this handle/PID or use its reap as refund evidence.
    returned[0].stdin.close();returned[0].wait(timeout=3)
    runtime.shutdown_safety()
    assert runtime.pool.snapshot()['occupied']==1


@pytest.mark.parametrize('payload',[b'',b'POST /v1/responses HTTP/1.1\r\nContent-Length: 100000\r\n\r\nx'])
def test_original_slow_header_or_body_connection_stop_is_bounded(diagnostic,payload):
    runtime,attempt,source=source_of(diagnostic)
    connection=socket.create_connection(source['server'].server_address,timeout=2)
    try:
        if payload:connection.sendall(payload)
        deadline=time.monotonic()+2
        while source['accepted'] is None and time.monotonic()<deadline:time.sleep(.005)
        assert source['accepted'] is not None
        began=time.monotonic();runtime.stop_to_terminal(diagnostic['lease'])
        assert time.monotonic()-began<5
        assert source['accepted'][0].fileno()==-1 and source['server'] is None
        assert not source['server_thread'].is_alive() and runtime.pool.snapshot()['occupied']==0
    finally:connection.close()


def test_actual_receiver_thread_start_failure_cleans_without_shutdown_deadlock(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);captured=[];original=threading.Thread.start
    def failed(thread):
        if getattr(thread,'_target',None) is not None and thread._target.__name__=='serve':
            captured.append(thread);raise RuntimeError('injected receiver thread start failure')
        return original(thread)
    began=time.monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread,'start',failed)
        with pytest.raises(RuntimeError,match='receiver thread start'):
            with isolated_session(tmp_path,approved=True,
                    confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']):
                pytest.fail('failed receiver cannot issue a runnable source')
    assert len(captured)==1 and captured[0].ident is None and time.monotonic()-began<30


def test_actual_listener_timeout_failure_retains_and_closes_original(tmp_path,monkeypatch):
    from rlflow.hybrid_native_diagnostic import NativeDiagnosticOwner
    tmp_path.chmod(0o700);servers=[];owners=[]
    server_init=http.server.HTTPServer.__init__;owner_init=NativeDiagnosticOwner.__init__
    timeout=socket.socket.settimeout
    def capture_server(server,*args,**kwargs):
        server_init(server,*args,**kwargs);servers.append(server)
    def capture_owner(owner,*args,**kwargs):
        owner_init(owner,*args,**kwargs);owners.append(owner)
    def failed(sock,value):
        if servers and sock is servers[-1].socket and value==.05:
            raise RuntimeError('injected original listener timeout failure')
        return timeout(sock,value)
    with monkeypatch.context() as patch:
        patch.setattr(http.server.HTTPServer,'__init__',capture_server)
        patch.setattr(NativeDiagnosticOwner,'__init__',capture_owner)
        patch.setattr(socket.socket,'settimeout',failed)
        with pytest.raises(RuntimeError,match='listener timeout failure'):
            with isolated_session(tmp_path,approved=True,
                    confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']):
                pytest.fail('partial allocation must not issue a runnable source')
    assert len(servers)==1 and servers[0].socket.fileno()==-1
    runtime=owners[0];attempt=next(iter(runtime._attempts.values()))
    assert not attempt['spawn_entered'] and not attempt['release_entered']
    with closing(sqlite3.connect('file:'+str(runtime.pool.root/'pool.db')+'?mode=ro',uri=True)) as db:
        heads=[json.loads(row[0]) for row in db.execute('SELECT raw FROM heads')]
    assert all(head is None or head['state']=='FREE' for head in heads)


def test_actual_accepted_fstat_failure_retains_unknown_and_prevents_new_effect(tmp_path,monkeypatch):
    tmp_path.chmod(0o700)
    manager=isolated_session(tmp_path,approved=True,
        confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash'])
    diagnostic=manager.__enter__()
    runtime,attempt,source=source_of(diagnostic)
    listener=source['server'].socket.fileno();retained=[];fault=threading.Event()
    accept=socket.socket.accept;fstat=os.fstat;peer=None
    def captured(sock):
        result=accept(sock)
        if sock.fileno()==listener:retained.append(result[0])
        return result
    def failed(fd):
        if retained and fd==retained[0].fileno() and not fault.is_set():
            fault.set();raise OSError(errno.EIO,'injected accepted original fstat failure')
        return fstat(fd)
    try:
        before=(runtime.store.version(),runtime.pool.snapshot()['version'])
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket,'accept',captured);patch.setattr(os,'fstat',failed)
            peer=socket.create_connection(source['server'].server_address,timeout=2)
            assert fault.wait(2)
            source['server_thread'].join(2)
            assert not source['server_thread'].is_alive() and source['receiver_stop'].is_set()
            assert source['accepted']==(retained[0],None) and source['status']=='UNKNOWN', (source['accepted'],source['status'])
            with pytest.raises(Conflict,match='identity UNKNOWN'):runtime.start(diagnostic['lease'])
            assert before==(runtime.store.version(),runtime.pool.snapshot()['version'])
            assert not attempt['spawn_entered'] and not attempt['release_entered'] and source['producer'] is None
            began=time.monotonic()
            with pytest.raises(Conflict,match='identity UNKNOWN'):runtime.stop_to_terminal(diagnostic['lease'])
            assert time.monotonic()-began<5
        # Product never resampled/adopted/closed the unknown original FD.
        fstat(retained[0].fileno())
        assert source['accepted']==(retained[0],None) and source['server'] is None
        assert all(fd is None for fd in source['fds'].values())
        assert attempt['terminal'] is None and runtime._current(attempt)['status']=='UNKNOWN'
        assert runtime.pool.snapshot()['occupied']==1
    finally:
        if peer is not None:peer.close()
        # Only the test independently retires its retained original socket;
        # this is not product adoption, terminal evidence or a refund.
        for connection in retained:connection.close()
        with pytest.raises(Conflict,match='identity UNKNOWN'):runtime.shutdown_safety()
        assert runtime._live and runtime._safety_freeze and attempt['terminal'] is None
        assert runtime.pool.snapshot()['occupied']==1
        # Unknown identity remains unprovable even after test-owned close.
        # The SDK must report incomplete cleanup, not synthesize FREE.
        with pytest.raises(Conflict):manager.__exit__(None,None,None)


def test_original_diagnostic_grant_copy_cannot_register_another_attempt(diagnostic):
    runtime,attempt,source=source_of(diagnostic);grant=attempt['diagnostic_grant']
    from rlflow.hybrid_native_diagnostic_gate import native_identity
    with pytest.raises(RuntimeError,match='native ELF'):native_identity(source['fds']['read'])
    with pytest.raises(PermissionError):runtime.register(attempt['bundle'],attempt['token'],attempt['observation'],attempt['claim'],
        request_key='copied',scenario='native_diagnostic',diagnostic_grant=NativeDiagnosticGrant(grant.id,grant.raw))
    with pytest.raises(Conflict):runtime.register(attempt['bundle'],attempt['token'],attempt['observation'],attempt['claim'],
        request_key='old',scenario='complete')
    assert source['producer'] is None and not attempt['spawn_entered']


def test_actual_kernel_rejects_new_process_but_permits_threads(tmp_path):
    from rlflow import hybrid_native_diagnostic_gate as gate
    home=tmp_path/'home';work=tmp_path/'work';home.mkdir(mode=0o700);work.mkdir(mode=0o700)
    script='''
import ctypes,errno,importlib.util,json,os,sys,threading
spec=importlib.util.spec_from_file_location('fixed_gate',sys.argv[1]);gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
libc=ctypes.CDLL(None,use_errno=True);fd=os.open(gate.NATIVE,os.O_RDONLY|os.O_CLOEXEC)
gate.restrict(fd,sys.argv[2],sys.argv[3]);result={}
try:os.fork();result['fork']=False
except OSError as error:result['fork']=error.errno==errno.EPERM
for name,number,args,wanted in [('vfork',58,(),errno.EPERM),('clone',56,(17,0,0,0,0),errno.EPERM),('clone3',435,(0,0),errno.ENOSYS),('io_uring',425,(1,0),errno.EPERM)]:
 result[name]=libc.syscall(number,*args)==-1 and ctypes.get_errno()==wanted
rows=[];thread=threading.Thread(target=lambda:rows.append('actual thread'));thread.start();thread.join(1);result['threads']=rows==['actual thread'] and not thread.is_alive()
try:os.execve('/usr/bin/true',['true'],{});result['foreign_exec']=False
except OSError as error:result['foreign_exec']=error.errno==errno.EACCES
print(json.dumps(result))
'''
    completed=subprocess.run([sys.executable,'-I','-c',script,str(Path(gate.__file__).resolve()),str(home),str(work)],
        capture_output=True,text=True,timeout=5)
    assert completed.returncode==0,completed.stderr
    assert json.loads(completed.stdout)==dict.fromkeys(('fork','vfork','clone','clone3','io_uring','threads','foreign_exec'),True)


def test_partial_allocation_reused_listener_fd_retains_scope_and_never_closes_foreign(tmp_path,monkeypatch):
    from rlflow.hybrid_native_diagnostic import NativeDiagnosticOwner
    tmp_path.chmod(0o700);servers=[];owners=[];descriptors={}
    server_init=http.server.HTTPServer.__init__;owner_init=NativeDiagnosticOwner.__init__
    start=threading.Thread.start
    def capture_server(server,*args,**kwargs):
        server_init(server,*args,**kwargs);servers.append(server)
    def capture_owner(owner,*args,**kwargs):
        owner_init(owner,*args,**kwargs);owners.append(owner)
    def failed(thread):
        if getattr(thread,'_target',None) is not None and thread._target.__name__=='serve':
            fd=servers[-1].socket.fileno();descriptors['listener']=fd;descriptors['backup']=os.dup(fd)
            foreign=os.open(tmp_path/'foreign.txt',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
            descriptors['foreign_identity']=(os.fstat(foreign).st_dev,os.fstat(foreign).st_ino)
            os.dup2(foreign,fd);os.close(foreign)
            raise RuntimeError('injected partial listener reuse before receiver thread start')
        return start(thread)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(http.server.HTTPServer,'__init__',capture_server)
            patch.setattr(NativeDiagnosticOwner,'__init__',capture_owner)
            patch.setattr(threading.Thread,'start',failed)
            with pytest.raises(RuntimeError,match='partial listener reuse'):
                with isolated_session(tmp_path,approved=True,
                        confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']):
                    pytest.fail('partial allocation must not issue a runnable source')
        info=os.fstat(descriptors['listener'])
        assert (info.st_dev,info.st_ino)==descriptors['foreign_identity']
        runtime=owners[0];attempt=next(iter(runtime._attempts.values()))
        assert attempt['source'] is None and attempt['terminal'] is None
        assert not attempt['spawn_entered'] and not attempt['release_entered']
        assert runtime._current(attempt)['status']=='UNKNOWN'
        with closing(sqlite3.connect('file:'+str(runtime.pool.root/'pool.db')+'?mode=ro',uri=True)) as db:
            heads=[json.loads(row[0]) for row in db.execute('SELECT raw FROM heads')]
        assert sum(head is not None and head['state']!='FREE' for head in heads)==1
        # Restore only this test's original socket, never adopt any new cap/PID.
        os.dup2(descriptors['backup'],descriptors['listener']);os.close(descriptors.pop('backup'))
        result=runtime.shutdown_safety()
        assert not result['pool_slots_freed'] and not result['refund_enabled']
        assert servers[0].socket.fileno()==-1
        with closing(sqlite3.connect('file:'+str(runtime.pool.root/'pool.db')+'?mode=ro',uri=True)) as db:
            heads=[json.loads(row[0]) for row in db.execute('SELECT raw FROM heads')]
        assert sum(head is not None and head['state']!='FREE' for head in heads)==1
    finally:
        if 'backup' in descriptors:
            os.dup2(descriptors['backup'],descriptors['listener']);os.close(descriptors['backup'])
        for runtime in owners:
            if runtime._live:runtime.shutdown_safety()
