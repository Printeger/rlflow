"""Actual finite-keeper kernel ownership, not Core/general-start acceptance."""
import json
import os
from pathlib import Path
import subprocess
import uuid
import pytest


@pytest.mark.parametrize('fail_close', [False, True, 'foreign'])
def test_original_task_scope_stops_descendants_before_closing_handles(tmp_path, fail_close):
    root = str(Path(__file__).resolve().parents[1])
    python = str(Path('/usr/bin/python3').resolve(strict=True))
    work = tmp_path/'work';work.mkdir(mode=0o700)
    code = f'''
import os,sys,ctypes,json,select,time,pathlib
sys.path.insert(0,{root!r})
from rlflow.hybrid_local_runner_cgroup import OriginalTaskScope
from rlflow.hybrid_local_runner_sandbox import confine
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
scope=OriginalTaskScope(dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
r,w=os.pipe()
producer=os.fork()
if producer==0:
 os.close(r)
 scope.enter_original_child()
 os.environ.clear()
 os.environ.update(PATH='/usr/bin:/bin',LANG='C.UTF-8',CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none')
 null=os.open('/dev/null',os.O_RDONLY);os.dup2(null,0);os.close(null)
 exe=os.open({python!r},os.O_PATH|os.O_CLOEXEC)
 loader=os.open('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',os.O_PATH|os.O_CLOEXEC)
 inputs=[os.open(p,os.O_PATH|os.O_CLOEXEC) for p in ('/usr/lib','/etc/ld.so.cache')]
 held=os.open({str(work)!r},os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC)
 confine((exe,loader),tuple(inputs),held)
 for fd in [exe,loader,held,*inputs]:os.close(fd)
 descendant=os.fork()
 if descendant==0:
  os.close(w);os.setsid()
  pathlib.Path({str(work/'descendant.json')!r}).write_text(json.dumps(dict(pid=os.getpid(),pgid=os.getpgrp())))
  while True:time.sleep(.05)
 while not pathlib.Path({str(work/'descendant.json')!r}).exists():time.sleep(.005)
 os.write(w,b'R');os.close(w)
 while True:time.sleep(.05)
os.close(w)
assert select.select([r],[],[],5)[0]
assert os.read(r,1)==b'R';os.close(r)
descendant=json.loads(pathlib.Path({str(work/'descendant.json')!r}).read_text())
assert descendant['pid']==descendant['pgid']
assert pathlib.Path('/proc/'+str(descendant['pid'])+'/cgroup').read_text().strip()=='0::'+scope._path+'/task'
assert not scope.task_empty()
try:scope.close_empty_task()
except RuntimeError:pass
else:raise RuntimeError('populated task incorrectly closed')
terminal=scope.stop_task(5)
assert terminal['task_empty'] and not terminal['whole_scope_stopped']
reaped,status=os.waitpid(producer,0)
assert reaped==producer and os.WIFSIGNALED(status) and os.WTERMSIG(status)==9
reaped_descendant,status=os.waitpid(descendant['pid'],0)
assert reaped_descendant==descendant['pid'] and os.WIFSIGNALED(status)
original_fds=(*scope._fds.values(),scope._task,scope._control,scope._root)
if {fail_close!r}:
 original_close=os.close
 target=scope._fds['cgroup.events']
 def fail_once(fd):
  if fd==target:raise OSError(5,'injected pre-close failure')
  return original_close(fd)
 os.close=fail_once
 try:
  try:scope.close_empty_task()
  except RuntimeError as exc:assert 'cleanup incomplete' in str(exc)
  else:raise RuntimeError('close failure concealed')
 finally:os.close=original_close
 assert scope._fds['cgroup.events']==target
 assert all(fd is None for name,fd in scope._fds.items() if name!='cgroup.events')
 assert scope._root is None and scope._control is None and scope._task is None
 assert os.fstat(target)
if {fail_close!r}=='foreign':
 # External test actor replaces a retained original FD. Original owner must
 # never close/adopt this foreign descriptor or claim successful cleanup.
 original_close(target)
 foreign=os.open('/dev/null',os.O_RDONLY)
 if foreign!=target:
  os.dup2(foreign,target);original_close(foreign);foreign=target
 try:scope.close_empty_task()
 except RuntimeError as exc:assert 'cleanup incomplete' in str(exc)
 else:raise RuntimeError('foreign FD incorrectly adopted or closed')
 assert os.fstat(foreign) and not scope._closed
 original_close(foreign)
 closed=dict(task_handles_closed=False,whole_scope_stopped=False,unknown=True)
else:
 closed=scope.close_empty_task()
 assert closed['task_handles_closed'] and not closed['whole_scope_stopped']
for fd in original_fds:
 try:os.fstat(fd)
 except OSError as exc:assert exc.errno==9
 else:raise RuntimeError('original scope FD leaked')
print(json.dumps(dict(terminal=terminal,closed=closed,producer_reaped=True,descendant_reaped=True)),flush=True)
'''
    unit='rlflow-local-'+uuid.uuid4().hex+'.service'
    command=['/usr/bin/systemd-run','--user','--pipe','--wait','--collect',
             '--unit='+unit,'--property=Delegate=cpu memory pids',
             '--property=MemoryMax=128M','--property=MemorySwapMax=0',
             '--property=TasksMax=16','--property=CPUQuota=100%',
             '--property=NoNewPrivileges=yes','--property=RestrictNamespaces=yes',
             '--property=RuntimeMaxSec=15',python,'-I','-S','-c',code]
    proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
                               'XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid()),
                               'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/'+str(os.getuid())+'/bus'})
    try:
        output,error=proc.communicate(timeout=20)
        (tmp_path/'actual-command.json').write_text(json.dumps(command))
        (tmp_path/'actual-stdout.txt').write_bytes(output)
        (tmp_path/'actual-stderr.txt').write_bytes(error)
        assert proc.returncode==0,error.decode()+output.decode()
        value=json.loads(output)
        assert value['producer_reaped'] and value['descendant_reaped']
        assert value['terminal']['memory_peak']>0
        assert 'usage_usec ' in value['terminal']['cpu_stat']
        assert value['closed']['task_handles_closed'] is (fail_close!='foreign')
        # The service client exits here; no Pool/lease or whole-scope proof is
        # inferred from its return value. A future original owner must bind
        # manager InvocationID/terminal status and all source FDs separately.
    finally:
        subprocess.run(['/usr/bin/systemctl','--user','stop',unit],capture_output=True,timeout=5)
        if proc.poll() is None:proc.kill();proc.communicate(timeout=5)


def test_cgroup_capability_cannot_be_reconstructed_in_controller():
    from rlflow.hybrid_local_runner_cgroup import OriginalTaskScope
    import pytest
    with pytest.raises(RuntimeError,match='new original project finite user service'):
        OriginalTaskScope(dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))


def test_failed_preparation_retains_original_temporary_close_owner(tmp_path):
    root=str(Path(__file__).resolve().parents[1])
    python=str(Path('/usr/bin/python3').resolve(strict=True))
    code=f'''
import os,sys,json
sys.path.insert(0,{root!r})
from rlflow.hybrid_local_runner_cgroup import OriginalTaskScope
original_close=os.close
def fail_temporary(fd):
 if os.readlink('/proc/self/fd/'+str(fd)).endswith('.service/cgroup.procs'):
  raise OSError(5,'injected preparation temporary close failure')
 return original_close(fd)
os.close=fail_temporary
try:
 try:OriginalTaskScope(dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
 except OSError as exc:scope=exc.original_scope_cleanup
 else:raise RuntimeError('preparation failure concealed')
finally:os.close=original_close
assert scope._root is None and not scope._closed
original=[fd for fd in scope._temporaries.values() if fd is not None]
assert len(original)==1 and os.fstat(original[0])
result=scope.retry_preparation_cleanup()
assert result['preparation_handles_closed'] and not result['whole_scope_stopped']
try:os.fstat(original[0])
except OSError as exc:assert exc.errno==9
else:raise RuntimeError('original temporary FD leaked')
print(json.dumps(result),flush=True)
'''
    unit='rlflow-local-'+uuid.uuid4().hex+'.service'
    result=subprocess.run(['/usr/bin/systemd-run','--user','--pipe','--wait','--collect',
        '--unit='+unit,'--property=Delegate=cpu memory pids','--property=RuntimeMaxSec=10',
        python,'-I','-S','-c',code],capture_output=True,timeout=15,
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid()),
             'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/'+str(os.getuid())+'/bus'})
    (tmp_path/'actual-stdout.txt').write_bytes(result.stdout)
    (tmp_path/'actual-stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode()+result.stdout.decode()
    assert json.loads(result.stdout)['preparation_handles_closed']
