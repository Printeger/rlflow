import os
from pathlib import Path
import subprocess
import sys
import pytest
from rlflow.resources import admit
from rlflow.store import Conflict


def policy(mode='strict'):
    return {'mode':mode,'memory_max':64*1024**2,'cpu_max':'20000 100000','pids_max':8,'disk_bytes':8*1024**2,'disk_inodes':64,'cpu_seconds':5}


def test_missing_hard_limits_are_never_claimed():
    with pytest.raises(Conflict,match='strict'):admit(policy())
    assert admit(policy('compatible_cpu'))=={'enforced':False,'missing_guarantees':['task cgroup','disk byte/inode hard quota']}


def test_actual_inherited_write_confinement(tmp_path):
    quota=tmp_path/'quota';quota.mkdir();outside=tmp_path/'outside';outside.write_text('original')
    code='''
from pathlib import Path
import subprocess,sys
from rlflow.resources import confine_writes
confine_writes(sys.argv[1])
Path(sys.argv[1],'allowed').write_text('allowed')
try:Path(sys.argv[2]).write_text('escape')
except PermissionError:pass
else:raise AssertionError('outside write allowed')
child=subprocess.run([sys.executable,'-c',"from pathlib import Path;Path("+repr(sys.argv[2])+").write_text('escape')"],capture_output=True)
assert child.returncode!=0
'''
    result=subprocess.run([sys.executable,'-c',code,str(quota),str(outside)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert outside.read_text()=='original' and (quota/'allowed').read_text()=='allowed'
