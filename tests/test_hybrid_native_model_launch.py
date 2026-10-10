"""Original native launch wiring; all G writes intercepted, zero model calls."""
import os
import subprocess

import pytest

from rlflow.hybrid_native_model_runtime import NativeModelLaunch
from rlflow.store import Conflict
from tests.test_hybrid_native_account_cache import account_original,original,native_setup,FILES

ACTUAL_POPEN=subprocess.Popen


def register(context):
    (owner,bundle,token,obs,claim),home=context
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='native_launch',
        scenario='native_model',native_model_grant=grant)
    return owner,lease,home


def test_original_start_reaches_intercepted_g_never_retries_and_stops(account_original,monkeypatch):
    owner,lease,home=register(account_original)
    attempt=owner._issued(lease);row=owner.sources._issued(attempt['source']);writes=[]
    with pytest.raises(PermissionError):owner.prepare_native_launch(lease)
    assert not owner._native_launches and row['producer'] is None
    owner.prepare_current_account_cache(lease)
    launch=owner.prepare_native_launch(lease)
    assert row['producer'] is None and not attempt['release_entered']
    with pytest.raises(Conflict):owner.prepare_native_launch(lease)
    with pytest.raises(PermissionError):owner.start(lease,launch=NativeModelLaunch(launch.id,launch.raw))
    assert not attempt['spawn_entered'] and row['producer'] is None
    class NoG:
        def __init__(self,pipe):self.pipe=pipe
        def fileno(self):return self.pipe.fileno()
        @property
        def closed(self):return self.pipe.closed
        def close(self):return self.pipe.close()
        def write(self,data):
            assert data==b'G';writes.append(data)
            raise PermissionError('TEST intercepted G before any model exec')
        def flush(self):pytest.fail('intercepted G must not flush')
    def python_gate_only(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        process=ACTUAL_POPEN(argv,*args,**kwargs);process.stdin=NoG(process.stdin)
        return process
    monkeypatch.setattr(subprocess,'Popen',python_gate_only)
    with pytest.raises(PermissionError,match='TEST intercepted G'):owner.start(lease,launch=launch)
    assert writes==[b'G'] and attempt['release_entered']
    assert owner._launch_active is None and owner._start_materials is None
    assert 'python' in os.readlink('/proc/'+str(row['producer'].pid)+'/exe')
    # Original lost-send latch: calling again never sends or spawns again.
    result=owner.start(lease,launch=launch)
    assert result['release_attempted'] and not result['source_authenticated']
    assert not result['account_qualified'] and not result['usage_qualified']
    assert writes==[b'G']
    result=owner.stop_to_terminal(lease)
    assert result['scope']=='FIXED_NATIVE_SINGLE_TGID' and not result['fixed_cpu_scope_only']
    assert row['producer'].poll() is not None and row['producer'].stdin.closed
    assert owner.pool.snapshot()['occupied']==0 and owner._current(attempt)['status']=='UNKNOWN'
    assert all(fd is None for fd in row['fds'].values())
    assert not owner.sources._account_caches[id(attempt['source'])].descriptors()
    assert (home/'auth.json').read_bytes()==b'{"synthetic":"NOT_A_TOKEN"}'
    with pytest.raises((Conflict,PermissionError,OSError)):owner.start(lease,launch=launch)
    assert owner.store.audit()==owner.store.replay()


def test_launch_copy_change_rejected_before_handoff(account_original,monkeypatch):
    owner,lease,_=register(account_original)
    owner.prepare_current_account_cache(lease)
    launch=owner.prepare_native_launch(lease)
    attempt=owner._issued(lease);row=owner.sources._issued(attempt['source'])
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('changed cache cannot spawn'))
    auth=row['path']/'auth-private'/'auth.json'
    auth.write_bytes(b'{"synthetic":"CHANGED_NOT_A_TOKEN"}')
    with pytest.raises(Conflict,match='input changed'):owner.start(lease,launch=launch)
    assert not attempt['spawn_entered'] and not attempt['release_entered']
    assert owner._current(attempt)['fixture_runtime']['phase']=='REGISTER_NO_HANDOFF'
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0 and owner._current(attempt)['status']=='SETTLED'
    assert owner.store.audit()==owner.store.replay()
