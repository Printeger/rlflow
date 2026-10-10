"""Actual irreversible kernel guard, not a model or recovered STOP grant."""
import json
from pathlib import Path
import subprocess


def test_post_fork_keeper_fence_denies_all_creation_and_exec_keeps_original_child(tmp_path):
    root=str(Path(__file__).resolve().parents[1])
    code=f'''
import sys,os,ctypes,errno,json
sys.path.insert(0,{root!r})
from rlflow.hybrid_local_runner_sandbox import close_keeper_producers
read,write=os.pipe()
pid=os.fork()
if not pid:
 os.close(write)
 assert os.read(read,1)==b'G'
 child=os.fork()
 if not child:
  os.setsid()
  os.execv('/usr/bin/true',['true'])
 assert os.waitpid(child,0)[1]==0
 os._exit(0)
os.close(read)
receipt=close_keeper_producers()
libc=ctypes.CDLL(None,use_errno=True)
denied=[]
for number in (56,57,58,59,322,425,426,427,435,450):
 ctypes.set_errno(0)
 result=libc.syscall(number,0,0,0,0,0,0)
 assert result==-1 and ctypes.get_errno()==errno.EPERM,(number,result,ctypes.get_errno())
 denied.append(number)
try:os.fork()
except PermissionError:pass
else:raise RuntimeError('keeper fork allowed')
os.write(write,b'G');os.close(write)
assert os.waitpid(pid,0)[1]==0
print(json.dumps(dict(receipt=receipt,denied=denied,original_child_fork_exec=True)),flush=True)
'''
    command=['/usr/bin/python3','-I','-S','-c',code]
    result=subprocess.run(command,capture_output=True,text=True,timeout=10)
    (tmp_path/'fence-command.json').write_text(json.dumps(command))
    (tmp_path/'fence-stdout.txt').write_text(result.stdout)
    (tmp_path/'fence-stderr.txt').write_text(result.stderr)
    assert result.returncode==0,result.stderr+result.stdout
    report=json.loads(result.stdout)
    assert report['original_child_fork_exec'] and len(report['denied'])==10
