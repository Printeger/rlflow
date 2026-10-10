"""Actual finite configured CPU service; NOT Core-authorized autonomy."""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import time
import uuid

import pytest


@pytest.mark.parametrize('stop', [False, True, 'preallocated'])
def test_configured_service_distinguishes_transport_keeper_task_and_closes(tmp_path, stop):
    preallocated=stop=='preallocated'
    stop=stop is True
    root = str(Path(__file__).resolve().parents[1])
    work = tmp_path/'work'
    work.mkdir(mode=0o700)
    code = """import os,pathlib,json,collections,time
data=['pear','plum','pear','apple','plum','pear']
result=dict(sorted(collections.Counter(data).items()))
pathlib.Path(WORK+'/counts.json').write_text(json.dumps(result))
os.write(1,json.dumps(result).encode()+b'\\n')
child=os.fork()
if not child:
 os.setsid()
 while True:time.sleep(1)
"""
    config = dict(code=code, work=str(work), stdout=str(tmp_path/'task-stdout'),
                  stderr=str(tmp_path/'task-stderr'), seconds=10,
                  limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
    if preallocated:
        identities={}
        for name in ('stdout','stderr'):
            output=Path(config[name]);output.write_bytes(b'');output.chmod(0o600)
            info=output.stat();identities[name]=[info.st_dev,info.st_ino,info.st_uid]
        config['output_identities']=identities
    raw = json.dumps(config, sort_keys=True).encode()
    config_path = tmp_path/'config.json'
    config_path.write_bytes(raw)
    config_path.chmod(0o600)
    config_hash = hashlib.sha256(raw).hexdigest()
    unit = 'rlflow-local-'+uuid.uuid4().hex+'.service'
    service = (f'import sys;sys.path.insert(0,{root!r});'
               'from rlflow.hybrid_local_runner_service import serve;'
               f'serve({str(config_path)!r},{config_hash!r})')
    command = ['/usr/bin/systemd-run','--user','--pipe','--wait',
               '--unit='+unit, '--property=Delegate=cpu memory pids',
               '--property=MemoryMax=128M','--property=MemorySwapMax=0',
               '--property=CPUQuota=100%','--property=TasksMax=16',
               '--property=NoNewPrivileges=yes','--property=RestrictNamespaces=yes',
               '--property=RuntimeMaxSec=15','--property=RemainAfterExit=yes',
               str(Path('/usr/bin/python3').resolve()),'-I','-S','-c',service]
    env = dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',XDG_RUNTIME_DIR='/run/user/'+str(os.getuid()),
               DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/'+str(os.getuid())+'/bus')
    process = subprocess.Popen(command, stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env, bufsize=0)
    protocol = b''
    def line():
        nonlocal protocol
        end = time.monotonic()+5
        while b'\n' not in protocol:
            assert time.monotonic()<end, 'original service protocol deadline exceeded'
            if select.select([process.stdout],[],[],.05)[0]:
                chunk = os.read(process.stdout.fileno(),16384)
                assert chunk, 'original service protocol closed early'
                protocol += chunk
                assert len(protocol)<=32768
        result,protocol = protocol.split(b'\n',1)
        return json.loads(result)
    try:
        ready = line()
        assert ready['type']=='local_cpu.ready' and ready['config_sha256']==config_hash
        assert len({process.pid,ready['keeper']['pid'],ready['task']['pid']})==3
        observed = subprocess.run(['/usr/bin/systemctl','--user','show',unit,
                    '--property=InvocationID,MainPID,ExecMainPID,ExecMainCode,ExecMainStatus,Result,ActiveState,SubState'],
                    env=env,capture_output=True,timeout=3,check=True).stdout.decode()
        before = dict(row.split('=',1) for row in observed.splitlines())
        assert before['InvocationID']==ready['keeper']['invocation_id']
        assert int(before['MainPID'])==ready['keeper']['pid']
        keeper_pidfd = os.pidfd_open(ready['keeper']['pid'])
        try:
            if stop:
                process.stdin.close()  # Controller EOF: zero candidate effects.
            else:
                assert process.stdin.write(b'G')==1
            closed = line()
            assert closed['type']=='local_cpu.task_closed'
            assert closed['keeper']==ready['keeper'] and closed['task']==ready['task']
            assert closed['original_output_fds_closed'] and closed['original_control_fd_closed']
            assert closed['closed']['keeper_protocol_handles_closed']
            assert closed['stopped']['task_empty'] and not closed['whole_scope_stopped']
            assert select.select([keeper_pidfd],[],[],5)[0]==[keeper_pidfd]
            observed_after = subprocess.run(['/usr/bin/systemctl','--user','show',unit,
                    '--property=InvocationID,MainPID,ExecMainPID,ExecMainCode,ExecMainStatus,Result,ActiveState,SubState'],
                    env=env,capture_output=True,timeout=3,check=True).stdout.decode()
            after = dict(row.split('=',1) for row in observed_after.splitlines())
            assert after['InvocationID']==ready['keeper']['invocation_id']
            assert int(after['ExecMainPID'])==ready['keeper']['pid']
            assert after['ExecMainCode']=='1' and after['ExecMainStatus']=='0'
            assert after['MainPID']=='0' and after['SubState']=='exited' and after['Result']=='success'
            (tmp_path/'manager-before.txt').write_text(observed)
            (tmp_path/'manager-after.txt').write_text(observed_after)
            (tmp_path/'protocol.json').write_text(json.dumps(dict(ready=ready,closed=closed)))
        finally:
            os.close(keeper_pidfd)
        if not stop:
            assert json.loads((work/'counts.json').read_text())==dict(apple=1,pear=3,plum=2)
            assert len(closed['stopped']['reaped'])==2
        else:
            assert not (work/'counts.json').exists()
            assert (tmp_path/'task-stdout').read_bytes()==b''
        assert (tmp_path/'task-stderr').read_bytes()==b''
    finally:
        if not process.stdin.closed:process.stdin.close()
        cleanup = subprocess.run(['/usr/bin/systemctl','--user','stop',unit],env=env,
                                 capture_output=True,timeout=5)
        process.wait(timeout=5)
        (tmp_path/'actual-command.json').write_text(json.dumps(command))
        (tmp_path/'actual-stderr.txt').write_bytes(process.stderr.read())
        (tmp_path/'manager-stop.json').write_text(json.dumps(dict(code=cleanup.returncode,
                                                    stdout=cleanup.stdout.decode(),stderr=cleanup.stderr.decode())))
        process.stdout.close();process.stderr.close()
    assert process.returncode==0


@pytest.mark.parametrize('fault', ['ready', 'control_close'])
def test_original_ready_report_failure_still_stops_reaps_and_closes(tmp_path, fault):
    root=str(Path(__file__).resolve().parents[1])
    work=tmp_path/'work';work.mkdir(mode=0o700)
    config=dict(code="import pathlib;pathlib.Path(WORK+'/forbidden').write_text('executed')",
                work=str(work),stdout=str(tmp_path/'task-stdout'),stderr=str(tmp_path/'task-stderr'),
                seconds=10,limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
    raw=json.dumps(config,sort_keys=True).encode()
    path=tmp_path/'config.json';path.write_bytes(raw);path.chmod(0o600)
    script=f'''
import sys,os,json
sys.path.insert(0,{root!r})
import rlflow.hybrid_local_runner_service as service
original_dup,original_close=os.dup,os.close
creator_pid=os.getpid()
control=[]
def captured_dup(fd):
 result=original_dup(fd)
 if fd==0:control.append(result)
 return result
def failed_control_close(fd):
 if os.getpid()==creator_pid and control and fd==control[0]:raise OSError(5,'injected original control close failure')
 return original_close(fd)
if {fault!r}=='control_close':
 os.dup=captured_dup;os.close=failed_control_close
def failed_report(value):raise OSError(5,'injected trusted ready report failure')
service._emit=failed_report
try:service.serve({str(path)!r},{hashlib.sha256(raw).hexdigest()!r})
except OSError as exc:
 cleanup=exc.original_service_cleanup
 assert cleanup['creator']['pid']==os.getpid()
 assert cleanup['control_identity'] is not None
 keeper=cleanup['keeper']
 assert keeper._closed and keeper._reaped and keeper._stop
 assert not keeper._released
 assert all(fd is None for fd,identity in cleanup['sources'])
 os.dup=original_dup;os.close=original_close
 if {fault!r}=='control_close':
  assert cleanup['control']==control[0]
  assert service._inode(cleanup['control'])==cleanup['control_identity']
  assert len(cleanup['failures'])==1 and cleanup['failures'][0][0]=='control'
  original_close(cleanup['control'])  # Exact original test actor only; no DTO adoption.
 else:
  assert cleanup['control'] is None and not cleanup['failures']
 os.write(1,json.dumps(dict(type='TEST_ONLY_FAILURE_CLEANUP',error=str(exc),
                 zero_g=True,task_reaped=True,original_fds_closed=True,
                 whole_scope_stopped=False)).encode()+b'\\n')
else:raise RuntimeError('original report failure concealed')
'''
    unit='rlflow-local-'+uuid.uuid4().hex+'.service'
    command=['/usr/bin/systemd-run','--user','--pipe','--wait','--collect',
             '--unit='+unit,'--property=Delegate=cpu memory pids',
             '--property=MemoryMax=128M','--property=MemorySwapMax=0',
             '--property=CPUQuota=100%','--property=TasksMax=16',
             '--property=NoNewPrivileges=yes','--property=RestrictNamespaces=yes',
             '--property=RuntimeMaxSec=15',str(Path('/usr/bin/python3').resolve()),'-I','-S','-c',script]
    result=subprocess.run(command,input=b'',capture_output=True,timeout=20,
            env=dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',XDG_RUNTIME_DIR='/run/user/'+str(os.getuid()),
                     DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/'+str(os.getuid())+'/bus'))
    (tmp_path/'actual-command.json').write_text(json.dumps(command))
    (tmp_path/'actual-stdout.txt').write_bytes(result.stdout)
    (tmp_path/'actual-stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode()+result.stdout.decode()
    report=json.loads(result.stdout)
    assert report['type']=='TEST_ONLY_FAILURE_CLEANUP' and report['zero_g']
    assert not report['whole_scope_stopped']
    assert not (work/'forbidden').exists()
    assert (tmp_path/'task-stdout').read_bytes()==b''
    assert (tmp_path/'task-stderr').read_bytes()==b''
