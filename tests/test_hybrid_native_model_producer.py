"""Real original Python gate/STOP, never Codex/model/auth execution."""
import json
import os
import subprocess

import pytest

from rlflow.hybrid_budget_ledger import SECTIONS,project_key
from rlflow.hybrid_usage_source import FixtureUsageSourceOwner
from tests.test_hybrid_a_workflow_derivation import original,native_setup,FILES

ACTUAL_POPEN=subprocess.Popen


def test_original_no_g_producer_stop_releases_physical_pool_not_unknown_tokens(original,monkeypatch):
    def python_gate_only(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        return ACTUAL_POPEN(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',python_gate_only)
    owner,bundle,token,obs,claim=original
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='native_producer',
        scenario='native_model',native_model_grant=grant)
    result=owner.prepare_no_release_producer(lease)
    assert result['sandbox_ready'] and not result['model_released'] and not result['account_qualified']
    attempt=owner._issued(lease);row=owner.sources._issued(attempt['source'])
    assert row['producer'].poll() is None and not attempt['release_entered']
    assert 'python' in os.readlink('/proc/'+str(row['producer'].pid)+'/exe')
    assert list((row['path']/'auth-private').iterdir())==[]
    assert os.pread(row['fds']['read'],1,0)==b''
    ready=json.loads(owner.sources._model_ready[id(attempt['source'])][1])
    assert ready['single_tgid'] and ready['packet_sealed'] and not ready['account_qualified']
    with pytest.raises(PermissionError):owner.sources._runtime_release(owner,lease)
    with pytest.raises(PermissionError):owner.start(lease)
    with pytest.raises(PermissionError):owner.sources.seal(attempt['source'])
    # Even bypassing the Source override must hit the original Owner's last
    # effect fence before any write to the actual control pipe.
    owner._write_phase(attempt,'RELEASE_INTENT')
    with owner.pool._lock,owner._gate(attempt,'RELEASE_INTENT'):
        with pytest.raises(PermissionError,match='no G at effect fence'):
            FixtureUsageSourceOwner._runtime_release(owner.sources,owner,lease)
    assert not attempt['release_entered'] and row['producer'].poll() is None
    assert 'python' in os.readlink('/proc/'+str(row['producer'].pid)+'/exe')
    owner.stop_to_terminal(lease)
    assert row['producer'].poll() is not None and row['producer'].stdin.closed
    assert all(fd is None for fd in row['fds'].values())
    assert owner.pool.snapshot()['occupied']==0
    current=owner._current(attempt)
    assert current['status']=='UNKNOWN'
    project=owner.store.get(SECTIONS[3],project_key(owner.workspace.project_id,'fixture'))
    assert project['reserved']==current['amount'] and project['unknown_exposure']==current['amount']
    assert owner.store.audit()==owner.store.replay()
