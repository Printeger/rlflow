"""New private report capture retains failed kernel sources, never grants."""
import os
import pytest
from rlflow.hybrid_local_cpu_retirement import _capture_report
from rlflow.hybrid_runtime_boundary import directory_chain
from rlflow.store import Conflict


@pytest.mark.parametrize('fault',('fstat','close'))
def test_private_capture_failure_retains_original_descriptor(tmp_path,monkeypatch,fault):
    tmp_path.chmod(0o700)
    report=tmp_path/'task-report';report.write_bytes(b'{}\n');report.chmod(0o600)
    info=report.stat();source={'path':str(tmp_path),'chain':directory_chain(tmp_path),
        'files':{'task-report':[info.st_dev,info.st_ino,info.st_uid]}}
    fstat=os.fstat;close=os.close;injected=[]
    def is_original(fd):
        try:return os.readlink(f'/proc/self/fd/{fd}')==str(report)
        except OSError:return False
    def fail_stat(fd):
        if fault=='fstat' and not injected and is_original(fd):
            injected.append(fd);raise OSError('injected original capture stat failure')
        return fstat(fd)
    def fail_close(fd):
        if fault=='close' and not injected and is_original(fd):
            injected.append(fd);raise OSError('injected original capture close failure')
        return close(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os,'fstat',fail_stat);patch.setattr(os,'close',fail_close)
        with pytest.raises(Conflict,match='retirement-report cleanup failed') as caught:_capture_report(source)
    retained=caught.value.original_recovery_kernel_fds
    assert len(injected)==1 and retained==[{'fd':injected[0],
        'identity':None if fault=='fstat' else (info.st_dev,info.st_ino),'source':'retirement-report'}]
    assert (fstat(injected[0]).st_dev,fstat(injected[0]).st_ino)==(info.st_dev,info.st_ino)
    close(injected[0])
