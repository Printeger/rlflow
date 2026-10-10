"""Real kernel substrate tests, NOT Core-authorized general Runner acceptance."""
import json
import os
from pathlib import Path
import select
import subprocess
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(Path('/usr/bin/python3').resolve(strict=True))


def _task(tmp_path, body):
    work = tmp_path / 'work'
    work.mkdir(mode=0o700)
    # Caller code and input are deliberately configurable, not add/pi profiles.
    preamble = f'''
import os,sys,json,pathlib,socket,subprocess
import select,time
sys.path.insert(0,{str(ROOT)!r})
from rlflow.hybrid_local_runner_sandbox import confine
work={str(work)!r}
group=pathlib.Path('/sys/fs/cgroup')/pathlib.Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
control=group/'control'; control.mkdir()
(control/'cgroup.procs').write_text(str(os.getpid()))
(group/'cgroup.subtree_control').write_text('+cpu +memory +pids')
task=group/'task'; task.mkdir()
for name,value in [('memory.max','134217728'),('memory.swap.max','0'),('cpu.max','100000 100000'),('pids.max','16'),('memory.oom.group','1')]:
 (task/name).write_text(value)
producer=os.fork()
if producer:
 _,status=os.waitpid(producer,0)
 if select.select([0],[],[],15)[0]: os.read(0,1)
 raise SystemExit(os.waitstatus_to_exitcode(status))
(task/'cgroup.procs').write_text(str(os.getpid()))
os.environ.clear()
os.environ.update(PATH='/usr/bin:/bin',LANG='C.UTF-8',CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none')
null=os.open('/dev/null',os.O_RDONLY); os.dup2(null,0); os.close(null)
exe=os.open({PYTHON!r},os.O_PATH|os.O_CLOEXEC)
loader=os.open('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',os.O_PATH|os.O_CLOEXEC)
inputs=[os.open(p,os.O_PATH|os.O_CLOEXEC) for p in ({str(ROOT)!r},'/usr/lib','/usr/lib64','/etc/ld.so.cache') if os.path.exists(p)]
held=os.open(work,os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC)
receipt=confine((exe,loader),tuple(inputs),held)
for fd in [exe,loader,held,*inputs]: os.close(fd)
'''
    unit = 'rlflow-cp83-test-' + uuid.uuid4().hex + '.service'
    command = ['/usr/bin/systemd-run', '--user', '--pipe', '--wait', '--collect',
               '--unit=' + unit, '--property=MemoryMax=128M',
               '--property=MemorySwapMax=0', '--property=CPUQuota=100%',
               '--property=TasksMax=16', '--property=NoNewPrivileges=yes',
               '--property=RestrictSUIDSGID=yes', '--property=RestrictNamespaces=yes',
               '--property=Delegate=cpu memory pids', '--property=RuntimeMaxSec=20',
               PYTHON, '-I', '-S', '-c', preamble + body]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                 'XDG_RUNTIME_DIR': '/run/user/' + str(os.getuid()),
                                 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/' + str(os.getuid()) + '/bus'})
    return proc, unit, work


def test_real_configurable_task_forks_execs_and_denies_external_effects(tmp_path):
    outside = tmp_path / 'protected.txt'
    outside.write_text('original')
    proc, unit, work = _task(tmp_path, f'''
denied=[]
for name,action in [
 ('outside_write',lambda:pathlib.Path({str(outside)!r}).write_text('changed')),
 ('user_bus',lambda:socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)),
 ('internet',lambda:socket.socket(socket.AF_INET,socket.SOCK_STREAM)),
 ('foreign_signal',lambda:os.kill({os.getpid()},0)),
 ('gpu_open',lambda:os.open('/dev/nvidiactl',os.O_RDWR)),
]:
 try: action()
 except OSError: denied.append(name)
 else: raise RuntimeError('external operation permitted: '+name)
candidate=pathlib.Path(work)/'candidate.py'
candidate.write_text('def unique_in_order(items):\\n    return list(dict.fromkeys(items))\\n')
validation="import runpy; f=runpy.run_path("+repr(str(candidate))+")["+repr('unique_in_order')+"]; assert f(['b','a','b','c','a'])==['b','a','c']; print('validated')"
child=subprocess.run([{PYTHON!r},'-I','-S','-c',validation],capture_output=True,text=True,timeout=3)
assert child.returncode==0,child.stderr
print(json.dumps(dict(receipt=receipt,denied=denied,child=child.stdout.strip())),flush=True)
''')
    output, error = proc.communicate(input=b'Q', timeout=15)
    assert proc.returncode == 0, error.decode() + output.decode()
    result = json.loads(output)
    assert result['child'] == 'validated'
    assert result['denied'] == ['outside_write', 'user_bus', 'internet', 'foreign_signal', 'gpu_open']
    assert result['receipt']['containment'] == 'REQUIRES_ORIGINAL_CGROUP_OWNER'
    assert outside.read_text() == 'original'
    assert (work / 'candidate.py').is_file()


def test_setsiding_descendant_remains_in_original_cgroup_and_is_stopped(tmp_path):
    # This proves the kernel route; a future owner still needs held directory
    # identity, original durable registration/release and FD/usage settlement.
    proc, unit, work = _task(tmp_path, '''
pid=os.fork()
if pid==0:
 os.setsid()
 pathlib.Path(work+'/child.json').write_text(json.dumps(dict(pid=os.getpid(),pgid=os.getpgrp())))
 import time
 while True: time.sleep(.05)
while not pathlib.Path(work+'/child.json').exists():
 import time
 time.sleep(.005)
print(pathlib.Path(work+'/child.json').read_text(),flush=True)
import time
while True: time.sleep(.05)
''')
    held = None
    events = None
    try:
        assert select.select([proc.stdout], [], [], 10)[0], 'task readiness timeout'
        child = json.loads(proc.stdout.readline())
        assert child['pid'] == child['pgid']
        group_value = subprocess.run(['/usr/bin/systemctl', '--user', 'show', unit,
                                      '--property=ControlGroup', '--value'],
                                     capture_output=True, text=True, check=True, timeout=3).stdout.strip()
        assert group_value.endswith('/' + unit)
        group_value += '/task'
        group = Path('/sys/fs/cgroup') / group_value.lstrip('/')
        held = os.open(group, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        events = os.open('cgroup.events', os.O_RDONLY | os.O_CLOEXEC, dir_fd=held)
        assert Path(f'/proc/{child["pid"]}/cgroup').read_text().strip() == '0::' + group_value
        members = (group / 'cgroup.procs').read_text().split()
        assert str(child['pid']) in members and str(os.getpid()) not in members
        limits = {n: (group/n).read_text().strip() for n in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        assert limits == {'memory.max':'134217728','memory.swap.max':'0','cpu.max':'100000 100000','pids.max':'16'}
        kill = os.open('cgroup.kill', os.O_WRONLY | os.O_CLOEXEC, dir_fd=held)
        try: assert os.write(kill, b'1') == 1
        finally: os.close(kill)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            os.lseek(events, 0, os.SEEK_SET)
            raw = os.read(events, 1024).decode()
            if 'populated 0' in raw.splitlines(): break
            time.sleep(.01)
        else: raise AssertionError('original cgroup still populated')
        output, error = proc.communicate(input=b'Q', timeout=5)
        assert proc.returncode != 0  # Stopped, not fabricated successful work.
    finally:
        # Only this uniquely named test unit, never a shared parent scope.
        subprocess.run(['/usr/bin/systemctl', '--user', 'stop', unit],
                       capture_output=True, timeout=5)
        if events is not None: os.close(events)
        if held is not None: os.close(held)
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


def test_outside_metadata_cgroup_migration_and_queued_signals_are_denied(tmp_path):
    protected = tmp_path/'original-ledger.txt'
    protected.write_text('original immutable evidence')
    before = protected.stat()
    parent_group = Path('/proc/self/cgroup').read_text().strip().split('::',1)[1]
    migration = str(Path('/sys/fs/cgroup') / parent_group.lstrip('/') / 'cgroup.procs')
    proc, unit, work = _task(tmp_path, f'''
import ctypes,errno
libc=ctypes.CDLL(None,use_errno=True)
def signal_queue(number):
 if libc.syscall(number,{os.getpid()},0,0)<0:
  raise OSError(ctypes.get_errno(),'queued signal blocked')
denied=[]
for name,action in [
 ('chmod',lambda:os.chmod({str(protected)!r},0o777)),
 ('utime',lambda:os.utime({str(protected)!r},ns=(1,1))),
 ('xattr',lambda:os.setxattr({str(protected)!r},'user.runner_escape',b'changed')),
 ('cgroup_migration',lambda:pathlib.Path({migration!r}).write_text(str(os.getpid()))),
 ('rt_sigqueueinfo',lambda:signal_queue(129)),
 ('rt_tgsigqueueinfo',lambda:signal_queue(297)),
]:
 try: action()
 except OSError as exc:
  assert exc.errno in (errno.EACCES,errno.EPERM),(name,exc)
  denied.append(name)
 else: raise RuntimeError('outside metadata/control effect permitted: '+name)
pathlib.Path(work+'/result.txt').write_text('ordinary candidate writes still work')
print(json.dumps(denied),flush=True)
''')
    output, error = proc.communicate(input=b'Q', timeout=15)
    assert proc.returncode == 0, error.decode() + output.decode()
    assert json.loads(output) == ['chmod','utime','xattr','cgroup_migration','rt_sigqueueinfo','rt_tgsigqueueinfo']
    after = protected.stat()
    assert (after.st_mode,after.st_mtime_ns,after.st_ctime_ns) == (before.st_mode,before.st_mtime_ns,before.st_ctime_ns)
    assert protected.read_text() == 'original immutable evidence'
    assert 'user.runner_escape' not in os.listxattr(protected)
    assert (work/'result.txt').read_text() == 'ordinary candidate writes still work'


def test_async_fcntl_cannot_signal_an_independent_victim(tmp_path):
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    victim = subprocess.Popen([PYTHON,'-I','-S','-c',
        "import signal,sys; signal.signal(signal.SIGIO,lambda *_:print('SIGNAL',flush=True)); print('READY',flush=True); sys.stdin.buffer.read(1)"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    try:
        assert select.select([victim.stdout],[],[],3)[0]
        assert victim.stdout.readline() == b'READY\n'
        priority=libc.syscall(252,1,victim.pid)
        assert priority>=0
        proc, unit, work = _task(tmp_path, f'''
import fcntl,errno,struct,ctypes
r,w=os.pipe()
denied=[]
for command,value in [(8,{victim.pid}),(10,29),(15,struct.pack('ii',1,{victim.pid})),(1024,fcntl.F_RDLCK),(1026,1),(4,os.O_ASYNC)]:
 try: fcntl.fcntl(r,command,value)
 except OSError as exc:
  assert exc.errno==errno.EPERM,(command,exc)
  denied.append(command)
 else: raise RuntimeError('async notification permitted')
try: fcntl.ioctl(r,0x541b,b'\\x00'*4)
except OSError as exc: assert exc.errno==errno.EPERM
else: raise RuntimeError('unqualified ioctl permitted')
libc=ctypes.CDLL(None,use_errno=True)
assert libc.syscall(251,1,{victim.pid},3<<13)==-1
assert ctypes.get_errno()==errno.EPERM
# Ordinary flags and descriptor operations remain usable for local tools.
fcntl.fcntl(r,fcntl.F_SETFL,os.O_NONBLOCK)
fcntl.fcntl(r,fcntl.F_SETFD,fcntl.FD_CLOEXEC)
os.write(w,b'x')
assert os.read(r,1)==b'x'
os.close(r);os.close(w)
print(json.dumps(denied),flush=True)
''')
        output,error=proc.communicate(input=b'Q',timeout=15)
        assert proc.returncode==0,error.decode()+output.decode()
        assert json.loads(output)==[8,10,15,1024,1026,4]
        assert victim.poll() is None
        assert libc.syscall(252,1,victim.pid)==priority
        output,error=victim.communicate(input=b'Q',timeout=3)
        assert victim.returncode==0 and output==b'' and error==b''
    finally:
        if victim.poll() is None:
            victim.kill();victim.communicate(timeout=3)
