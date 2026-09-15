"""Deterministic control-plane fixtures. No real Codex/LLM sessions are launched."""
import json
from pathlib import Path
import subprocess
import sys
import shlex
from types import SimpleNamespace

import pytest
from rlflow import engine, cli, isolation
from rlflow.contracts import role_schema
from rlflow.policy import candidate, new_stage
from rlflow.store import Store, Conflict, atomic, canonical

REAL_PACKET = engine.packet


def sample(schema):
    if 'const' in schema: return schema['const']
    if 'enum' in schema: return schema['enum'][0]
    if 'anyOf' in schema: return sample(schema['anyOf'][0])
    kind = schema.get('type')
    if kind == 'object': return {k: sample(v) for k, v in schema.get('properties', {}).items() if k in schema.get('required', [])}
    if kind == 'array': return []
    if kind == 'integer': return schema.get('minimum', 0)
    if kind == 'boolean': return False
    if kind == 'null': return None
    return '0' * 64 if 'pattern' in schema else 'fixture'


@pytest.fixture
def harness(tmp_path, monkeypatch):
    root = tmp_path / 'state'
    repo = root / 'workspaces' / 'demo'
    repo.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'parser.py').write_text('def parse(value):\n    return value\n')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@local', 'commit', '-qm', 'baseline'], check=True)
    store = Store(root)
    stage = new_stage('CPU', repo, 'reject invalid budgets', {'role_calls': 8, 'wall_seconds': 60, 'fake_starts': 2}, 'test-only')
    stage['per_call_seconds'] = 5
    store.transact('FIXTURE_STAGE', 'stage', lambda s: s['stages'].update(CPU=stage))
    task_id = engine.add_task(store, 'CPU', 'reject invalid budgets')
    monkeypatch.setattr(isolation, 'require_doctor', lambda root: {'passed': True})
    original_popen = subprocess.Popen
    # Only the worker launch is simulated; Git and other CPU utilities stay real.
    def popen(argv, *args, **kwargs):
        if 'rlflow.worker' in argv:
            return SimpleNamespace(pid=99999999)
        return original_popen(argv, *args, **kwargs)
    monkeypatch.setattr(engine.subprocess, 'Popen', popen)
    def packet(store, state, task, session):
        expected = {'schema_version': 'rlflow/0.2', 'role': session['role'], 'session_id': session['id'],
                    'task_id': task['id'], 'task_version': task['version'], 'cycle_id': task['cycle_id'],
                    'input_state_version': session['input_state_version']}
        return 'deterministic fixture, never sent to an LLM', expected
    monkeypatch.setattr(engine, 'packet', packet)
    return SimpleNamespace(store=store, repo=repo, task_id=task_id)


def result_for(h, sid, verdict='PASS'):
    state = h.store.replay()
    session = state['sessions'][sid]
    directory = Path(session['directory'])
    result = sample(role_schema(session['role']))
    result.update(json.loads((directory / 'expected.json').read_text()))
    result['candidate'] = engine.envelope_candidate(state['tasks'][h.task_id])
    payload = result['payload']
    if session['role'] == 'PI':
        payload.update(decision='ENGINEERING_DIAGNOSIS', task_interpretation={
            'goal': 'reject invalid budgets', 'module_roots': ['.'], 'acceptance_criteria': ['negative and wrong types rejected'],
            'stage_id': 'CPU', 'budget': {'role_calls': 8, 'wall_seconds': 60, 'fake_starts': 2}})
    elif session['role'] == 'Engineer':
        payload.update(candidate=result['candidate'], changes=[{'path': 'parser.py', 'description': 'validate inputs', 'suggested_category': 'ENGINEERING_FIX'}],
                       self_tests=[{'argv': ['python3', '-m', 'unittest'], 'exit_code': 0,
                                    'stdout_path': str(directory / 'scratch/stdout.log'), 'stderr_path': str(directory / 'scratch/stderr.log')}],
                       suggested_categories=['ENGINEERING_FIX'])
        argv = [sys.executable, '-c', 'import runpy; ns=runpy.run_path("parser.py"); assert ns["parse"](1)==1']
        execution = subprocess.run(argv, cwd=h.repo, capture_output=True, text=True)
        payload['self_tests'][0]['argv'] = argv
        payload['self_tests'][0]['exit_code'] = execution.returncode
        (directory / 'scratch/stdout.log').write_text(execution.stdout)
        (directory / 'scratch/stderr.log').write_text(execution.stderr)
    elif session['role'] == 'Evaluator':
        payload.update(verdict=verdict, conclusion_layer='CPU', evidence_coverage=['deterministic fixture coverage'], suggested_categories=['ENGINEERING_FIX'])
        argv = [sys.executable, '-c', 'import runpy; ns=runpy.run_path("parser.py"); assert ns["parse"](0)==0']
        execution = subprocess.run(argv, cwd=h.repo, capture_output=True, text=True)
        audit = {'argv': argv, 'command': shlex.join(argv), 'cwd': str(h.repo),
                 'exit_code': execution.returncode, 'stdout': execution.stdout, 'stderr': execution.stderr,
                 'timed_out': False}
        atomic(directory / 'result.json.commands.jsonl', canonical(audit) + b'\n')
        if verdict == 'FAIL':
            f = sample(role_schema('Evaluator')['properties']['payload']['properties']['findings']['items'])
            f.update(id='negative-budget', category='MUST_FIX', description='negative budget still accepted')
            payload['findings'] = [f]
    return result


def test_role_packet_contains_registered_evidence_mapping(harness):
    h = harness
    h.store.transact('FIXTURE_EVIDENCE','host evidence',lambda s:s['evidence'].update({
        'E-HOST':{'id':'E-HOST','event_sequence':1,'path':'/saved/host-evidence.json',
                  'sha256':'1'*64,'summary':'five non-skipped process-group tests passed',
                  'counterevidence':['CPU-only; no real runtime conclusion']}}))
    state=h.store.replay()
    session={'id':'S-packet','role':'Evaluator','input_state_version':state['version'],
             'scratch':'/scratch','role_definition':{'developer_instructions':'evaluate'}}
    prompt,_=REAL_PACKET(h.store,state,state['tasks'][h.task_id],session)
    assert '/saved/host-evidence.json' in prompt
    assert 'five non-skipped process-group tests passed' in prompt


def deliver(h, sid, result=None, elapsed=1, code=0):
    session = h.store.replay()['sessions'][sid]
    directory = Path(session['directory'])
    result = result or result_for(h, sid)
    atomic(directory / 'result.json', canonical(result))
    atomic(directory / 'receipt.json', canonical({'session_id': sid, 'exit_code': code, 'elapsed_seconds': elapsed, 'finished': 1, 'reason': 'fixture', 'model_usage': {'state': 'USED', 'source': 'simulated-worker'}}))
    engine.accept_result(h.store, sid)
    return h.store.replay()


def implement(h):
    sid = engine.dispatch_one(h.store)
    assert h.store.replay()['sessions'][sid]['role'] == 'Engineer'
    (h.repo / 'parser.py').write_text('def parse(value):\n    if type(value) is not int or value < 0:\n        raise ValueError("invalid budget")\n    return value\n')
    return deliver(h, sid)


def test_automatic_rework_fixture(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    implement(h)
    sid = engine.dispatch_one(h.store)
    state = deliver(h, sid, result_for(h, sid, 'FAIL'))
    assert state['tasks'][h.task_id]['next_role'] == 'Engineer'
    assert state['tasks'][h.task_id]['repair_rounds'] == 1
    implement(h)
    state = deliver(h, engine.dispatch_one(h.store))
    assert state['tasks'][h.task_id]['status'] == 'DONE'
    assert state['tasks'][h.task_id]['completion']['cpu'] is True
    assert state['tasks'][h.task_id]['completion']['real_run'] is False
    assert state['stages']['CPU']['used_calls'] == 5
    assert state['stages']['CPU']['used_seconds'] == 5
    assert state['stages']['CPU']['reserved_seconds'] == 0


def test_duplicate_task_and_result_no_double_charge(harness):
    h = harness
    assert engine.add_task(h.store, 'CPU', 'reject invalid budgets') == h.task_id
    sid = engine.dispatch_one(h.store)
    assert engine.dispatch_one(h.store) is None
    state = deliver(h, sid)
    engine.accept_result(h.store, sid)
    assert h.store.replay() == state
    assert state['stages']['CPU']['used_calls'] == 1


def test_start_failure_keeps_reservation_and_reconciles(harness, monkeypatch):
    h = harness
    original = subprocess.Popen
    def failed(argv, *args, **kwargs):
        if 'rlflow.worker' in argv: raise OSError('fixture crash window')
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(engine.subprocess, 'Popen', failed)
    with pytest.raises(OSError): engine.dispatch_one(h.store)
    state = engine.reconcile(Store(h.store.root))
    session = next(iter(state['sessions'].values()))
    assert session['status'] == 'RECONCILE'
    assert state['stages']['CPU']['used_calls'] == 0
    assert state['stages']['CPU']['reserved_seconds'] == 5
    assert state['stages']['CPU']['reserved_calls'] == 1
    assert engine.dispatch_one(h.store) is None


def test_stop_and_pause_prevent_reservations(harness):
    h = harness
    (h.store.root / 'STOP').touch()
    assert engine.dispatch_one(h.store) is None
    (h.store.root / 'STOP').unlink()
    h.store.transact('PAUSE', 'pause', lambda s: s.update(paused=True))
    assert engine.dispatch_one(h.store) is None
    assert h.store.replay()['stages']['CPU']['used_calls'] == 0


def test_stale_result_cannot_advance_task(harness):
    h = harness
    sid = engine.dispatch_one(h.store)
    result = result_for(h, sid)
    h.store.transact('FIXTURE_REVISE', 'revise', lambda s: s['tasks'][h.task_id].update(version=99))
    state = deliver(h, sid, result)
    assert state['sessions'][sid]['status'] == 'REJECTED'
    assert state['tasks'][h.task_id]['version'] == 99
    assert state['tasks'][h.task_id]['next_role'] == 'PI'
    assert state['stages']['CPU']['used_seconds'] == 1


def test_role_failure_consumes_budget(harness):
    h = harness
    sid = engine.dispatch_one(h.store)
    state = deliver(h, sid, code=7)
    assert state['sessions'][sid]['status'] == 'REJECTED'
    assert state['tasks'][h.task_id]['status'] == 'ROLE_ERROR'
    assert engine.dispatch_one(h.store) is None
    assert state['stages']['CPU']['used_calls'] == 1
    assert state['stages']['CPU']['used_seconds'] == 1
    assert state['stages']['CPU']['reserved_seconds'] == 0


def test_budget_hard_stop_shared_by_new_task(harness):
    h = harness
    h.store.transact('FIXTURE_BUDGET', 'budget', lambda s: s['stages']['CPU'].update(used_calls=8))
    assert engine.dispatch_one(h.store) is None
    assert h.store.replay()['tasks'][h.task_id]['status'] == 'BUDGET_EXHAUSTED'
    h.store.transact('FIXTURE_STOP_TASK', 'stop-task', lambda s: s['tasks'][h.task_id].update(status='STOPPED'))
    other = engine.add_task(h.store, 'CPU', 'another parser task')
    assert engine.dispatch_one(h.store) is None
    assert h.store.replay()['tasks'][other]['status'] == 'BUDGET_EXHAUSTED'


def test_readonly_candidate_drift_rejected(harness):
    h = harness
    sid = engine.dispatch_one(h.store)
    (h.repo / 'parser.py').write_text('unauthorized drift\n')
    state = deliver(h, sid)
    assert state['sessions'][sid]['status'] == 'REJECTED'
    assert 'candidate changed' in state['sessions'][sid]['error']


def test_unknown_changed_file_cannot_pass_classification(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    implement(h)
    (h.repo / 'new.py').write_text('external change\n')
    sid = engine.dispatch_one(h.store)
    if sid is None:
        assert h.store.replay()['tasks'][h.task_id]['status'] in {'CONTRACT_DECISION', 'RECONCILE'}
    else:
        state = deliver(h, sid)
        assert state['tasks'][h.task_id]['status'] == 'CONTRACT_DECISION'


def test_transaction_interrupt_and_rebuild(harness, monkeypatch):
    h = harness
    before = h.store.replay()
    def broken(s):
        s['stages']['CPU']['used_calls'] += 1
        raise RuntimeError('crash before commit')
    with pytest.raises(RuntimeError): h.store.transact('FAIL', 'failure', broken)
    assert h.store.replay() == before
    def fail_export(*args): raise OSError('projection write failed after commit')
    with monkeypatch.context() as m:
        m.setattr(h.store, '_export', fail_export)
        with pytest.raises(OSError):
            h.store.transact('DURABLE', 'durable', lambda s: s.update(paused=True))
    assert Store(h.store.root).replay()['paused'] is True
    state = h.store.rebuild()
    assert json.loads((h.store.root / 'state/RESEARCH_STATE.json').read_text()) == state
    h.store.transact('DURABLE', 'durable', lambda s: s.update(paused=False))
    assert h.store.replay() == state


def test_job_status_cli(harness, capsys):
    from rlflow import jobs
    h = harness
    # Actual tiny CPU fake process, independent of mocked role supervisor.
    assert cli.main(['--state-dir', str(h.store.root), 'submit-experiment', '--stage', 'CPU', '--key', 'fixture']) == 0
    state = h.store.replay()
    jid = next(iter(state['jobs']))
    for proc in jobs._CHILDREN: proc.wait(timeout=5)
    assert cli.main(['--state-dir', str(h.store.root), 'job-status', jid]) == 0
    assert h.store.replay()['jobs'][jid]['status'] == 'SUCCEEDED'


@pytest.mark.parametrize('elapsed', [-1, True, '1', None])
def test_invalid_receipt_keeps_full_reservation(harness, elapsed):
    h = harness
    sid = engine.dispatch_one(h.store)
    state = deliver(h, sid, elapsed=elapsed)
    assert state['sessions'][sid]['status'] == 'RECONCILE'
    assert state['stages']['CPU']['reserved_seconds'] == 5
    assert state['stages']['CPU']['reserved_calls'] == 1
    assert state['stages']['CPU']['used_calls'] == 0
    assert state['stages']['CPU']['used_seconds'] == 0
    assert engine.dispatch_one(h.store) is None


def test_second_same_finding_triggers_diagnosis(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    for _ in range(2):
        implement(h)
        sid = engine.dispatch_one(h.store)
        state = deliver(h, sid, result_for(h, sid, 'FAIL'))
    assert state['tasks'][h.task_id]['repair_rounds'] == 2
    assert state['tasks'][h.task_id]['status'] == 'QUEUED'
    assert state['tasks'][h.task_id]['next_role'] == 'Critic'


def test_frozen_contract_change_requires_decision(harness):
    h = harness
    h.store.transact('FIXTURE_PROTECT', 'protect', lambda s: s['stages']['CPU'].update(protected_paths=['parser.py']))
    deliver(h, engine.dispatch_one(h.store))
    state = implement(h)
    assert state['tasks'][h.task_id]['status'] == 'CONTRACT_DECISION'
    assert not state['tasks'][h.task_id]['completion']['cpu']


def test_worker_stdin_is_bounded_and_release_is_bound(tmp_path, monkeypatch):
    from rlflow import worker, jobs
    import os
    import sys
    import time
    d = tmp_path / 'role'
    d.mkdir()
    scratch = d / 'scratch'
    scratch.mkdir()
    request = {'id': 'S-fixture', 'directory': str(d), 'scratch': str(scratch), 'repo': str(tmp_path),
               'root': str(tmp_path), 'role': 'PI', 'schema': 'unused', 'limit': .15, 'prompt': 'x' * 1000000}
    atomic(d / 'request.json', canonical(request))
    atomic(d / 'release', canonical({'session': request['id'], 'identity': jobs.identity(os.getpid())}))
    monkeypatch.setattr(isolation, 'codex_command', lambda *args, **kwargs: ([sys.executable, '-c', 'import time; time.sleep(20)'], dict(os.environ)))
    started = time.monotonic()
    worker.run(d / 'request.json')
    receipt = json.loads((d / 'receipt.json').read_text())
    assert time.monotonic() - started < 2
    assert receipt['exit_code'] != 0
    assert 'prompt delivery' in receipt['reason']
    assert not jobs.owns(json.loads((d / 'codex-identity.json').read_text()))
    d2 = tmp_path / 'bad-role'; d2.mkdir()
    request.update(directory=str(d2))
    atomic(d2 / 'request.json', canonical(request))
    atomic(d2 / 'release', canonical({'session': 'another-session', 'identity': jobs.identity(os.getpid())}))
    worker.run(d2 / 'request.json')
    assert 'identity mismatch' in json.loads((d2 / 'receipt.json').read_text())['reason']
    assert not (d2 / 'codex-identity.json').exists()


def test_job_reservation_crash_never_resubmits(harness, monkeypatch):
    from rlflow import jobs
    h = harness
    called = []
    def failed(*args, **kwargs):
        called.append(True)
        raise OSError('fixture died after reservation before durable job launch')
    monkeypatch.setattr(jobs, 'submit', failed)
    argv = ['--state-dir', str(h.store.root), 'submit-experiment', '--stage', 'CPU', '--key', 'crashed']
    assert cli.main(argv) == 2
    assert cli.main(argv) == 0
    state = h.store.replay()
    assert len(called) == 1
    assert next(iter(state['jobs'].values()))['status'] == 'RECONCILE'
    assert state['stages']['CPU']['used_fake_starts'] == 1


def test_evaluator_without_command_audit_rejected(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    implement(h)
    sid = engine.dispatch_one(h.store)
    result = result_for(h, sid)
    d = Path(h.store.replay()['sessions'][sid]['directory'])
    (d / 'result.json.commands.jsonl').unlink()
    state = deliver(h, sid, result)
    assert state['sessions'][sid]['status'] == 'REJECTED'
    assert not state['tasks'][h.task_id]['completion']['cpu']


def test_engineer_missing_or_external_selftest_evidence_rejected(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    sid = engine.dispatch_one(h.store)
    result = result_for(h, sid)
    result['payload']['self_tests'][0]['stdout_path'] = str(h.repo / 'parser.py')
    state = deliver(h, sid, result)
    assert state['sessions'][sid]['status'] == 'REJECTED'
    assert 'scratch' in state['sessions'][sid]['error']


def test_worker_reaps_background_group_after_normal_exit(tmp_path, monkeypatch):
    from rlflow import worker, jobs
    import os
    d = tmp_path / 'role'; d.mkdir()
    scratch = d / 'scratch'; scratch.mkdir()
    request = {'id': 'S-fixture', 'directory': str(d), 'scratch': str(scratch), 'repo': str(tmp_path),
               'root': str(tmp_path), 'role': 'PI', 'schema': 'unused', 'limit': 2, 'prompt': ''}
    atomic(d / 'request.json', canonical(request))
    atomic(d / 'release', canonical({'session': request['id'], 'identity': jobs.identity(os.getpid())}))
    script = ('import subprocess,sys; from pathlib import Path; '
              'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(20)"]); '
              'Path("background.pid").write_text(str(p.pid))')
    monkeypatch.setattr(isolation, 'codex_command', lambda *args, **kwargs: ([sys.executable, '-c', script], dict(os.environ)))
    worker.run(d / 'request.json')
    receipt = json.loads((d / 'receipt.json').read_text())
    assert receipt['exit_code'] == 0
    pid = int((scratch / 'background.pid').read_text())
    import time
    deadline = time.monotonic() + 1
    while jobs.identity(pid) and time.monotonic() < deadline:
        time.sleep(.01)
    assert jobs.identity(pid) is None


@pytest.mark.parametrize('event,code,expected', [
    ({'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'rlflow_cpu',
      'tool': 'cpu_exec', 'status': 'failed', 'error': {'message':
      'MCP tool call requires approval, but approval policy is never'}}}, 0, 'CPU_EXEC_APPROVAL_REQUIRED'),
    ({'type': 'turn.failed', 'error': {'message': json.dumps({'error': {'code': 'invalid_json_schema'}})}},
     1, 'OUTPUT_SCHEMA_REJECTED'),
    ({'type': 'turn.failed', 'error': {'message': 'connection closed'}}, 1, 'ROLE_TRANSPORT_ERROR'),
])
def test_infrastructure_failure_blocks_without_double_charge(harness, event, code, expected):
    h = harness
    sid = engine.dispatch_one(h.store)
    d = Path(h.store.replay()['sessions'][sid]['directory'])
    atomic(d / 'events.jsonl', canonical(event) + b'\n')
    state = deliver(h, sid, code=code)
    task = state['tasks'][h.task_id]
    assert task['status'] == 'INFRASTRUCTURE_ERROR'
    assert task['last_failure']['code'] == expected
    assert task['repair_rounds'] == 0
    assert not task['results']
    assert engine.dispatch_one(Store(h.store.root)) is None
    engine.accept_result(h.store, sid)
    assert h.store.replay() == state
    assert state['stages']['CPU']['used_calls'] == 1
    assert state['stages']['CPU']['used_seconds'] == 1
    assert state['stages']['CPU']['reserved_seconds'] == 0
    h.store.transact('FIXTURE_QUEUE', 'queue-blocked', lambda s: s['tasks'][h.task_id].update(status='QUEUED'))
    assert engine.dispatch_one(Store(h.store.root)) is None


def test_reconsider_saved_pass_after_classifier_repair_without_double_charge(harness, monkeypatch):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    implement(h)
    h.store.transact('FIXTURE_TEST_LABEL', 'test-label', lambda state:
                     state['tasks'][h.task_id]['results'][-1]['payload']['changes'][0].update(
                         suggested_category='TEST'))
    sid = engine.dispatch_one(h.store)
    result = result_for(h, sid)
    result['payload']['suggested_categories'].append('TEST')
    with monkeypatch.context() as context:
        context.setattr(engine, 'infrastructure_failure', lambda directory: 'CPU_EXEC_TRANSPORT_ERROR')
        rejected = deliver(h, sid, result)
    assert rejected['tasks'][h.task_id]['status'] == 'INFRASTRUCTURE_ERROR'
    before_calls = rejected['stages']['CPU']['used_calls']
    before_seconds = rejected['stages']['CPU']['used_seconds']
    state = engine.reconsider_result(h.store, sid)
    assert state['sessions'][sid]['status'] == 'ACCEPTED'
    assert state['tasks'][h.task_id]['status'] == 'DONE'
    assert state['tasks'][h.task_id]['completion']['cpu'] is True
    assert state['stages']['CPU']['status'] == 'HOLD'
    assert state['stages']['CPU']['used_calls'] == before_calls
    assert state['stages']['CPU']['used_seconds'] == before_seconds
    assert h.task_id not in state.get('autonomous_tasks', [])
    assert engine.reconsider_result(h.store, sid) == state


def test_repeated_invalid_output_stops_automatic_dispatch(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    for expected_status in ('QUEUED', 'REPEATED_BLOCKER'):
        sid = engine.dispatch_one(h.store)
        result = result_for(h, sid)
        result['payload']['self_tests'] = []
        state = deliver(h, sid, result)
        assert state['tasks'][h.task_id]['status'] == expected_status
    assert state['tasks'][h.task_id]['last_failure']['kind'] == 'ROLE_OUTPUT'
    assert engine.dispatch_one(Store(h.store.root)) is None
    assert state['stages']['CPU']['used_calls'] == 3
    assert state['tasks'][h.task_id]['repair_rounds'] == 0


def test_candidate_comments_cannot_clear_the_same_validation_blocker(harness):
    h = harness
    deliver(h, engine.dispatch_one(h.store))
    for n in range(2):
        sid = engine.dispatch_one(h.store)
        (h.repo / 'parser.py').write_text(f'def parse(value):\n    return value  # {n}\n')
        result = result_for(h, sid)
        result['payload']['self_tests'] = []
        state = deliver(h, sid, result)
        assert state['tasks'][h.task_id]['status'] == ('QUEUED' if n==0 else 'REPEATED_BLOCKER')
        assert state['tasks'][h.task_id]['last_failure']['repeated'] == (n==1)


def test_infrastructure_does_not_hide_contract_drift(harness):
    h = harness
    sid = engine.dispatch_one(h.store)
    d = Path(h.store.replay()['sessions'][sid]['directory'])
    atomic(d / 'events.jsonl', canonical({'type': 'turn.failed', 'error': {'message': 'transport error'}}) + b'\n')
    (h.repo / 'parser.py').write_text('unauthorized change')
    state = deliver(h, sid)
    assert state['tasks'][h.task_id]['status'] == 'CONTRACT_DECISION'
    assert state['tasks'][h.task_id]['last_failure']['kind'] == 'CONTRACT'


def test_explicit_step_while_daemon_paused_still_obeys_stop_and_budget(harness):
    h = harness
    h.store.transact('PAUSE', 'operator-pause', lambda s: s.update(paused=True))
    assert engine.dispatch_one(h.store) is None
    (h.store.root / 'STOP').touch()
    assert engine.dispatch_one(h.store, allow_paused=True) is None
    (h.store.root / 'STOP').unlink()
    sid = engine.dispatch_one(h.store, allow_paused=True)
    assert sid
    assert engine.dispatch_one(h.store, allow_paused=True) is None
    state = deliver(h, sid)
    assert state['paused'] is True
    h.store.transact('FIXTURE_BUDGET', 'exhaust-step', lambda s: s['stages']['CPU'].update(used_calls=8))
    assert engine.dispatch_one(h.store, allow_paused=True) is None
    assert h.store.replay()['tasks'][h.task_id]['status'] == 'BUDGET_EXHAUSTED'


def test_packet_summarizes_candidate_file_manifest(harness, monkeypatch):
    h = harness
    monkeypatch.undo()
    state = h.store.replay()
    task = state['tasks'][h.task_id]
    captured = {}
    def build(value):
        captured.update(value)
        return {'packet': value, 'sha256': '0' * 64, 'token_count': 1,
                'tokenizer': 'fixture', 'source_state_version': value['version']}
    monkeypatch.setattr(engine, 'build_pi_packet', build)
    session = {'id': 'S-packet', 'role': 'PI', 'input_state_version': state['version'],
               'scratch': str(h.store.root / 'scratch'),
               'role_definition': engine.load_role('PI')}
    engine.packet(h.store, state, task, session)
    summary = captured['task']['baseline']
    assert 'files' not in summary
    assert summary['file_count'] == len(task['baseline']['files'])
    assert len(summary['files_sha256']) == 64
    task['accepted_candidate'] = task['baseline']
    captured.clear()
    engine.packet(h.store, state, task, session)
    assert 'files' not in captured['task']['accepted_candidate']


def test_packet_failure_closes_unlaunched_intent_releasing_reservation(harness, monkeypatch):
    h = harness
    def fail(*args, **kwargs):
        raise RuntimeError('packet fixture failure')
    monkeypatch.setattr(engine, 'packet', fail)
    with pytest.raises(RuntimeError, match='packet fixture failure'):
        engine.dispatch_one(h.store)
    state = h.store.replay()
    session = next(reversed(state['sessions'].values()))
    assert session['status'] == 'REJECTED'
    assert session['identity'] is None
    assert state['tasks'][h.task_id]['status'] == 'QUEUED'
    assert state['stages']['CPU']['used_calls'] == 0
    assert state['stages']['CPU']['reserved_seconds'] == 0



def test_candidate_diff_includes_untracked_without_mutating_index(harness):
    h = harness
    before = (h.repo / '.git/index').read_bytes()
    (h.repo / 'new_test.py').write_text('assert True\n')
    task = h.store.replay()['tasks'][h.task_id]
    diff = engine.git_diff_bytes(h.repo, task['baseline']['head'])
    assert b'new_test.py' in diff
    assert b'assert True' in diff
    assert (h.repo / '.git/index').read_bytes() == before

@pytest.mark.parametrize('roots,allowed,expected', [
    (['parser.py'], ['.'], True),
    (['src/parser.py'], ['src'], True),
    (['src2/parser.py'], ['src'], False),
    (['.'], ['src'], False),
    (['../escape'], ['.'], False),
    (['src/../escape'], ['src'], False),
    (['/tmp/file'], ['.'], False),
    ([], ['.'], False),
])
def test_pi_interpretation_may_only_narrow_scope(roots, allowed, expected):
    interpretation = {'stage_id':'CPU','module_roots':roots}
    assert engine.interpretation_matches_stage(interpretation, {'id':'CPU','module_roots':allowed}) is expected
    assert not engine.interpretation_matches_stage(interpretation, {'id':'OTHER','module_roots':allowed})


def test_pi_narrow_scope_dispatches_engineer(harness):
    sid = engine.dispatch_one(harness.store)
    result = result_for(harness, sid)
    result['payload']['task_interpretation']['module_roots'] = ['parser.py']
    state = deliver(harness, sid, result)
    assert state['tasks'][harness.task_id]['status'] == 'QUEUED'
    assert state['tasks'][harness.task_id]['next_role'] == 'Engineer'
