"""Consumer error cleanup, not a fabricated original Runtime capability."""
import os
import subprocess
import sys
from types import SimpleNamespace

from rlflow.isolated_finite_example import close_fixture


def test_failed_first_cleanup_does_not_abandon_real_child_or_other_FD(tmp_path):
    child=subprocess.Popen([sys.executable,'-I','-S','-c','import time;time.sleep(30)'],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    fd=os.open(tmp_path/'owned',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    events=[]
    class First:
        _live=True
        def shutdown(self):
            events.append('failed-first');raise OSError('injected original normal close failure')
        def shutdown_safety(self):
            events.append('first-safety');self._live=False
    class Second:
        _live=True
        def shutdown(self):
            events.append('second-real-close');child.terminate();child.wait(timeout=3);os.close(fd);self._live=False
    class Host:
        def cancel_all(self):
            events.append('all-latched');return []
    class Pool:
        _live=True
        def shutdown(self):events.append('pool-close');self._live=False
    try:
        errors=close_fixture(Host(),None,None,SimpleNamespace(close=lambda:events.append('socket-close')),
            [Second(),First()],[],Pool())
        assert len(errors)==1 and isinstance(errors[0],OSError)
        assert events==['all-latched','socket-close','failed-first','first-safety','second-real-close','pool-close']
        assert child.poll() is not None
        try:os.fstat(fd)
        except OSError:pass
        else:raise AssertionError('owned FD not closed')
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=3)
