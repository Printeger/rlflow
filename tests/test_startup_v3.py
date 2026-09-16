import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from rlflow.jobs import identity
from rlflow.store import atomic,canonical


def held(tmp_path):
    request={'directory':str(tmp_path),'owner':identity(os.getpid()),'root':str(tmp_path),'scratch':str(tmp_path),
             'argv':[sys.executable,'-c',"from pathlib import Path;Path('starts').write_text('1')"],
             'session':'s','generation':'new-generation','release_wait_seconds':20,'deadline':time.monotonic()+25}
    atomic(tmp_path/'held.json',canonical(request))
    child=subprocess.Popen([sys.executable,'-m','rlflow.lifeguard','held-role',str(tmp_path/'held.json')],start_new_session=True)
    until=time.monotonic()+5
    while not (tmp_path/'codex-identity.json').exists():
        if time.monotonic()>until:child.kill();child.wait();pytest.fail('held child failed readiness')
        time.sleep(.01)
    return child,json.loads((tmp_path/'codex-identity.json').read_text())


def test_actual_late_release_after_original_ten_second_window(tmp_path):
    child,owned=held(tmp_path)
    try:
        time.sleep(10.5)
        assert child.poll() is None and not (tmp_path/'starts').exists()
        atomic(tmp_path/'model-release.json',canonical({'session':'s','generation':'new-generation','identity':owned}))
        assert child.wait(timeout=5)==0
        assert (tmp_path/'starts').read_text()=='1'
        assert json.loads((tmp_path/'launch-start_ack.json').read_text())['binding']['generation']=='new-generation'
    finally:
        if child.poll() is None:child.kill();child.wait()


def test_stale_generation_never_executes(tmp_path):
    child,owned=held(tmp_path)
    try:
        atomic(tmp_path/'model-release.json',canonical({'session':'s','generation':'old-generation','identity':owned}))
        assert child.wait(timeout=5)==126
        assert not (tmp_path/'starts').exists()
    finally:
        if child.poll() is None:child.kill();child.wait()
