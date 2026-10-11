"""Actual repository baseline diagnosis, NOT an executed model-task closure."""
import hashlib
import json
from pathlib import Path
import time

from rlflow.hybrid_engineering_candidate import Candidate,verification_spec
from rlflow.hybrid_goals import digest
from rlflow.isolated_local_cpu import isolated_session
from rlflow.store import canonical


ROOT=Path(__file__).resolve().parents[1]
FILES={'rlflow/web_auth.py':'45784a12cc8d310e959796705164d5dad12b065fc398ac1359cc73b7c276bea0',
    'rlflow/__init__.py':'667d4a15b970b851e20d17510224670c14646cfb6d5a1e388ca6b9cc6da8bf41'}


def test_actual_dashboard_baseline_fails_frozen_external_rule_in_managed_cpu(tmp_path):
    tmp_path.chmod(0o700)
    files={}
    for name,expected in FILES.items():
        raw=(ROOT/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
        files[name]=raw.decode('utf-8')
    # No model patch, no local repair. Original repository bytes only.
    candidate=Candidate(digest(files),digest({'baseline_only':True}),digest(files),canonical(files))
    task=json.loads((ROOT/'validation/a_dashboard_auth_task.json').read_text())
    assert task['source_files_sha256']==FILES and task['execution_consent']=='UNAPPROVED'
    checks=(ROOT/task['checks_path']).read_text()
    assert hashlib.sha256(checks.encode()).hexdigest()==task['checks_sha256']
    spec=verification_spec(candidate,checks=checks,seconds=task['cpu_seconds'],acceptance=task['cpu_acceptance'])
    with isolated_session(tmp_path,spec,approved=True,
            confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source']);runtime.start(lease)
        deadline=time.monotonic()+15
        while row['task_closed'] is None:
            runtime.poll(lease);assert time.monotonic()<deadline;time.sleep(.02)
        result=runtime.collect_local_result(lease)
        assert result['execution']['status']=='SUCCEEDED'
        assert json.loads(result['outputs']['stdout']['text'])=={'cases':27,'passed':25,'failed':2}
        assert result['machine_acceptance']['status']=='FAIL'
        assert not result['condition_evidence']
        runtime.stop_to_terminal(lease)
        assert runtime._current(attempt)['status']=='SETTLED' and runtime.pool.snapshot()['occupied']==0
        assert all(fd is None for fd in row['fds'].values())
        assert runtime.store.audit()==runtime.store.replay()
    for name,expected in FILES.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected


def test_external_checks_reject_surrogate_handler_clearing_all_live_sessions(monkeypatch):
    from rlflow.web_auth import AuthStore
    from validation.a_dashboard_auth_checks import measure
    original_resolve=AuthStore.resolve
    def destructive(self,token,method):
        try:return original_resolve(self,token,method)
        except UnicodeEncodeError:
            self._sessions.clear();return None
    monkeypatch.setattr(AuthStore,'resolve',destructive)
    result=measure()
    assert result['cases']==27 and result['failed']>0 and result['passed']<27


def test_frozen_real_task_input_is_external_data_without_runtime_consent():
    task=json.loads((ROOT/'validation/a_dashboard_auth_task.json').read_text())
    assert task['execution_consent']=='UNAPPROVED'
    assert task['candidate_paths']==['rlflow/web_auth.py']
    assert task['source_files_sha256']==FILES
    checks=(ROOT/task['checks_path']).read_bytes()
    assert hashlib.sha256(checks).hexdigest()==task['checks_sha256']
    assert task['cpu_acceptance']=={'method':'JSON_METRICS_RANGE','metrics':{
        'cases':{'min':27,'max':27},'passed':{'min':27,'max':27},
        'failed':{'min':0,'max':0}},'stderr_empty':True}
    from rlflow.hybrid_a_workflow_profile import validate_spec
    from tests.test_hybrid_a_workflow_profile import spec
    value=spec();value.update(candidate_paths=task['candidate_paths'],checks=checks.decode(),
        cpu_seconds=task['cpu_seconds'],cpu_acceptance=task['cpu_acceptance'],
        continuation_task=task['continuation_task'])
    assert validate_spec(value)['continuation_task']==task['continuation_task']
