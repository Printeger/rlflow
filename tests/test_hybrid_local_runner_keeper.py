"""Real held CPU gate/STOP protocol, not Core-authorized model execution."""
import json
import os
from pathlib import Path
import subprocess
import uuid

import pytest


@pytest.mark.parametrize('release', [False, True, 'bad_ready', 'lost_fork',
                                     'wrong_owner', 'pidfd_signal', 'close_fault',
                                     'control_eof', 'producer_exit','extra_scope'])
def test_original_keeper_blocks_pre_g_and_closes_release_after_stop(tmp_path, release):
    root=str(Path(__file__).resolve().parents[1])
    python=str(Path('/usr/bin/python3').resolve(strict=True))
    work=tmp_path/'work';work.mkdir(mode=0o700)
    task="import pathlib,os,time; pathlib.Path(WORK+'/actual.txt').write_text('configured task executed'); os.write(1,b'actual output\\n'); time.sleep(10)"
    if release == 'producer_exit':
        task="""import pathlib,os,time,collections,json
counts=collections.Counter(['red','blue','red','green','blue','red'])
pathlib.Path(WORK+'/actual.txt').write_text(json.dumps(dict(sorted(counts.items()))))
os.write(1,b'actual output\\n')
child=os.fork()
if not child:
 os.setsid()
 while True:time.sleep(1)
"""
    code=f'''
import sys,os,json,time,pathlib
sys.path.insert(0,{root!r})
from rlflow.hybrid_local_runner_cgroup import OriginalTaskScope
from rlflow.hybrid_local_runner_keeper import FiniteCpuKeeper
scope=OriginalTaskScope(dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
keeper=FiniteCpuKeeper(scope)
control_read,control_write=os.pipe2(os.O_CLOEXEC)
out=os.open({str(tmp_path/'source-stdout.txt')!r},os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
err=os.open({str(tmp_path/'source-stderr.txt')!r},os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
read,fork=os.read,os.fork
if {release!r}=='bad_ready':
 def bad_ready(fd,size):
  if fd==keeper._ready:return b'{{}}'
  return read(fd,size)
 os.read=bad_ready
if {release!r}=='lost_fork':
 def lost_fork():
  pid=fork()
  if pid:raise OSError(5,'injected lost fork return')
  return pid
 os.fork=lost_fork
try:
 if {release!r} in ('bad_ready','lost_fork'):
  try:keeper.prepare_gate({task!r},{str(work)!r},out,err,seconds=10)
  except (OSError,RuntimeError):pass
  else:raise RuntimeError('unknown preparation concealed')
  assert not keeper._ready_proved
  try:keeper.release_gate()
  except RuntimeError:pass
  else:raise RuntimeError('G after failed original readiness')
  ready=dict(unknown=True)
 else:
  ready=keeper.prepare_gate({task!r},{str(work)!r},out,err,seconds=10)
  assert ready['pid']==keeper._producer
finally:os.read=read;os.fork=fork
assert not pathlib.Path({str(work/'actual.txt')!r}).exists()
if {release!r}=='extra_scope':
 os.mkdir('unrelated',dir_fd=scope._root)
 try:keeper.release_gate()
 except RuntimeError as error:assert 'additional cgroups' in str(error)
 else:raise RuntimeError('G despite extra managed scope')
 assert not keeper._released
if {release!r} is True:
 keeper.release_gate()
 deadline=time.monotonic()+3
 while not pathlib.Path({str(work/'actual.txt')!r}).exists():
  assert time.monotonic()<deadline
  time.sleep(.005)
if {release!r}=='wrong_owner':
 import threading
 failures=[]
 def foreign_thread():
  for method in (keeper.stop_and_reap_task,keeper.close_stopped_task):
   try:method()
   except RuntimeError:failures.append('denied')
 worker=threading.Thread(target=foreign_thread);worker.start();worker.join()
 assert failures==['denied','denied'] and not keeper._stop
 child=os.fork()
 if not child:
  try:
   for method in (keeper.stop_and_reap_task,keeper.close_stopped_task):
    try:method()
    except RuntimeError:pass
    else:os._exit(1)
   os._exit(0)
  except BaseException:os._exit(2)
 assert os.waitpid(child,0)[1]==0 and not keeper._stop
 os.fstat(keeper._gate);os.fstat(keeper._ready);os.fstat(keeper._pidfd)
if {release!r}=='pidfd_signal':
 import signal
 original_signal=signal.pidfd_send_signal
 def failed_signal(*args):raise OSError(5,'injected original pidfd signal error')
 signal.pidfd_send_signal=failed_signal
if {release!r} in ('control_eof','producer_exit'):
 if {release!r}=='control_eof':os.close(control_write)
 else:assert os.write(control_write,b'G')==1
 stopped=keeper.run_original_control(control_read)
 assert stopped['control_terminal_reason']==('CONTROL_EOF' if {release!r}=='control_eof' else 'PRODUCER_EXIT')
 if {release!r}=='producer_exit':
  assert len(stopped['reaped'])==2
  assert json.loads(pathlib.Path({str(work/'actual.txt')!r}).read_text())==dict(blue=2,green=1,red=3)
  os.close(control_write)
else:
 stopped=keeper.stop_and_reap_task()
 os.close(control_write)
os.close(control_read)
if {release!r}=='pidfd_signal':
 signal.pidfd_send_signal=original_signal
 assert stopped['protocol_cleanup_unknown'] and keeper._reaped
assert stopped['stop_latched'] and stopped['task_empty'] and not stopped['whole_scope_stopped']
try:keeper.release_gate()
except RuntimeError:pass
else:raise RuntimeError('late G after STOP')
try:keeper.prepare_gate({task!r},{str(work)!r},out,err,seconds=10)
except RuntimeError:pass
else:raise RuntimeError('second producer after STOP')
if {release!r}=='close_fault':
 original_close=os.close;failed_fd=keeper._ready
 def failed_close(fd):
  if fd==failed_fd:raise OSError(5,'injected original ready close error')
  return original_close(fd)
 os.close=failed_close
 try:
  try:keeper.close_stopped_task()
  except RuntimeError:pass
  else:raise RuntimeError('partial close concealed')
 finally:os.close=original_close
 assert keeper._ready==failed_fd and keeper._pidfd is None and keeper._gate is None
 assert not keeper._closed
 os.fstat(failed_fd)
if {release!r}=='extra_scope':
 try:keeper.close_stopped_task()
 except RuntimeError as error:assert 'additional cgroups' in str(error)
 else:raise RuntimeError('closed proof despite extra managed scope')
 assert not keeper._closed and not scope._closing
 os.rmdir('unrelated',dir_fd=scope._root)  # Original test-created EMPTY group only.
closed=keeper.close_stopped_task()
assert closed['keeper_protocol_handles_closed'] and not closed['whole_scope_stopped']
os.close(out);os.close(err)
print(json.dumps(dict(ready=ready,stopped=stopped,closed=closed)),flush=True)
'''
    unit='rlflow-local-'+uuid.uuid4().hex+'.service'
    command=['/usr/bin/systemd-run','--user','--pipe','--wait','--collect',
        '--unit='+unit,'--property=Delegate=cpu memory pids',
        '--property=MemoryMax=128M','--property=MemorySwapMax=0',
        '--property=CPUQuota=100%','--property=TasksMax=16',
        '--property=NoNewPrivileges=yes','--property=RestrictNamespaces=yes',
        '--property=RuntimeMaxSec=15',python,'-I','-S','-c',code]
    result=subprocess.run(command,capture_output=True,timeout=20,
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid()),
             'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/'+str(os.getuid())+'/bus'})
    (tmp_path/'actual-command.json').write_text(json.dumps(command))
    (tmp_path/'actual-stdout.txt').write_bytes(result.stdout)
    (tmp_path/'actual-stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode()+result.stdout.decode()
    value=json.loads(result.stdout)
    executed=release is True or release=='producer_exit'
    assert value['stopped']['release_attempted'] is executed
    assert (work/'actual.txt').exists() is executed
    assert (tmp_path/'source-stdout.txt').read_bytes()==(b'actual output\n' if executed else b'')
    assert (tmp_path/'source-stderr.txt').read_bytes()==b''
