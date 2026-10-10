from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import copy, deepcopy
import json
import os
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from rlflow.hybrid_agent_requests import AgentRequestService
from rlflow.hybrid_control import ControlError
from rlflow.hybrid_drafts import DraftService
from rlflow.hybrid_goals import SECTIONS, digest
from rlflow.store import Store, Conflict, canonical, sha
from rlflow.web_api import create_app
from rlflow.web_auth import AuthStore, Credential, Principal
from tests.test_hybrid_control_api import setup as core_setup, ORIGIN, PHRASE, BASE, login, submit_payload


def setup(tmp_path):
    store, auth, proposal, _, pair, projects, mono = core_setup(tmp_path)
    service = AgentRequestService(pair.drafts)
    principal = Principal('proposal_agent', 'agent', {'viewer'}, {'project_fixture'})
    agent, _ = auth.issue_request_token(principal, ttl=50)
    human, access = auth.login('operator', PHRASE)
    args = {'token': human, 'csrf': access.csrf, 'origin': ORIGIN}
    app = create_app(projects, auth, origin=ORIGIN, control_services={'project_fixture': pair},
                     agent_request_services={'project_fixture': service})
    return store, auth, proposal, service, agent, args, app, mono


def submit(service, proposal, token, key='original'):
    return service.submit(proposal, token=token, idempotency_key=key, expected_revision=proposal['contract_version'] - 1)


def forward(service, saved, args, version=0):
    return service.forward(saved['request_id'], request_hash=saved['request_hash'], expected_version=version, **args)


def test_goal_suggestion_real_human_draft_and_original_source_not_current_head(tmp_path, monkeypatch):
    store, auth, proposal, service, agent, args, _, _ = setup(tmp_path)
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected worker')))
    before = store.audit()
    saved = submit(service, proposal, agent)
    assert saved['status'] == 'AWAITING_HUMAN' and saved['result'] is None
    assert submit(service, proposal, agent) == saved and store.audit() == before
    accepted = forward(service, saved, args)
    assert accepted['status'] == 'ADOPTED' and accepted['result']['result']['state'] == 'DRAFT'
    assert accepted['forwarded_by'] == {'id': 'operator', 'kind': 'human'}
    assert store.objects(SECTIONS[0])[0][1]['submitted_by'] == accepted['forwarded_by']
    assert not store.objects('tasks') and not store.objects('sessions') and not store.objects('approvals')
    second = deepcopy(proposal); second['contract_version'] = 2
    service.drafts.submit(second, **args, idempotency_key='second', expected_revision=1, expected_state_version=1)
    report = service.get(saved['request_id'], token=agent, method='request')
    assert report['status'] == 'ADOPTED' and report['result'] == accepted['result']
    assert 'proposal' not in report and 'forwarded_by' not in report
    store.snapshot(); assert store.audit() == store.recover() == store.replay()


def test_real_core_commit_lost_return_and_cold_same_actor_reconcile(tmp_path, monkeypatch):
    store, auth, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    original = service.drafts.submit
    def lost(*a, **k):
        original(*a, **k)
        raise OSError('synthetic return lost after actual Core commit')
    monkeypatch.setattr(service.drafts, 'submit', lost)
    with pytest.raises(OSError): forward(service, saved, args)
    assert store.version() == 1
    assert service.get(saved['request_id'], token=agent, method='request')['status'] == 'ADOPTED'
    # Restart reconstructs no execution owner; only this non-authoritative
    # inbox plus a fresh explicitly provisioned original DraftService.
    cold = Store(store.root)
    actor = Principal('operator', 'human', {'operator'}, {'project_fixture'})
    cold_auth = AuthStore([Credential.create(actor, PHRASE)])
    draft = DraftService(cold, cold_auth, project_id='project_fixture', data_mode='fixture', origin=ORIGIN)
    reopened = AgentRequestService(draft)
    fresh, access = cold_auth.login('operator', PHRASE)
    result = forward(reopened, saved, {'token': fresh, 'csrf': access.csrf, 'origin': ORIGIN})
    assert result['status'] == 'ADOPTED' and cold.version() == 1
    assert len(cold.objects(SECTIONS[2])) == 1


def test_inbox_claim_commit_lost_ack_preserves_unknown_and_same_key(tmp_path, monkeypatch):
    store, auth, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    original = sqlite3.connect; fail = [True]
    class AckLost(sqlite3.Connection):
        armed = False
        def execute(self, sql, *a, **k):
            if sql.startswith('UPDATE requests SET claim='):
                self.armed = True
            return super().execute(sql, *a, **k)
        def commit(self):
            super().commit()
            if self.armed and fail[0]:
                fail[0] = False
                raise OSError('synthetic inbox commit ACK lost')
    def connect(path, *a, **k):
        if str(path).endswith('agent-requests.sqlite3'):
            k['factory'] = AckLost
        return original(path, *a, **k)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    with pytest.raises(OSError): forward(service, saved, args)
    assert store.version() == 0
    report = service.get(saved['request_id'], token=agent, method='request')
    assert report['status'] == 'UNKNOWN' and report['result'] is None
    other, access = auth.login('both', PHRASE)
    with pytest.raises(Conflict): forward(service, saved, {'token': other, 'csrf': access.csrf, 'origin': ORIGIN})
    assert forward(service, saved, args)['status'] == 'ADOPTED'
    assert store.version() == 1 and len(store.objects(SECTIONS[2])) == 1


def test_concurrent_different_humans_cannot_create_two_drafts(tmp_path):
    store, auth, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    token, access = auth.login('both', PHRASE)
    other = {'token': token, 'csrf': access.csrf, 'origin': ORIGIN}
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(forward, service, saved, a) for a in (args, other)]
        results = []
        for job in jobs:
            try: results.append(job.result(timeout=5)['status'])
            except Conflict: results.append('CONFLICT')
    assert sorted(results) == ['ADOPTED', 'CONFLICT']
    assert store.version() == 1 and len(store.objects(SECTIONS[2])) == 1


def test_known_stale_frozen_version_has_no_core_effect_or_auto_rebase(tmp_path):
    store, _, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    store.transact_objects('USAGE_OBSERVED', 'unrelated', [('usage', 'other')], lambda s: s.setdefault('usage', {}).update(other={}))
    before = store.audit()
    with pytest.raises(Conflict): forward(service, saved, args)
    assert service.get(saved['request_id'], token=agent, method='request')['status'] == 'STALE'
    with pytest.raises(Conflict): forward(service, saved, args, version=1)
    assert store.audit() == before and not store.objects(SECTIONS[0])


@pytest.mark.parametrize('change', ['revoke', 'expiry'])
def test_request_writer_wait_checks_actual_token_after_wait(tmp_path, monkeypatch, change):
    store, auth, proposal, service, agent, _, _, mono = setup(tmp_path)
    before = store.audit(); started = threading.Event(); original = service._db
    @contextmanager
    def observed(**kwargs):
        started.set()
        with original(**kwargs) as db: yield db
    monkeypatch.setattr(service, '_db', observed)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with service._lock:
            job = executor.submit(submit, service, proposal, agent)
            assert started.wait(2)
            if change == 'revoke': auth.revoke(agent)
            else: mono[0] = 52
        with pytest.raises(PermissionError): job.result(timeout=5)
    assert store.audit() == before
    with sqlite3.connect(service.path) as db: assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 0


@pytest.mark.parametrize('change', ['receipt', 'event_payload', 'event_missing'])
def test_corrupt_original_core_source_never_reports_adopted(tmp_path, change):
    store, _, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent); accepted = forward(service, saved, args)
    command = accepted['result']['command_id']
    with store.connect() as db:
        if change == 'receipt':
            db.execute('DELETE FROM projection WHERE section=? AND object_key=?', (SECTIONS[2], command))
        elif change == 'event_missing':
            with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM events WHERE idempotency_key=?', (command,))
            db.execute('DROP TRIGGER no_delete')  # disposable corruption fixture only
            db.execute('DELETE FROM events WHERE idempotency_key=?', (command,))
        else:
            row = db.execute('SELECT payload FROM events WHERE idempotency_key=?', (command,)).fetchone()
            value = json.loads(row[0]); value['put'] = [v for v in value['put'] if v[0] != SECTIONS[1]]
            with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE events SET payload=? WHERE idempotency_key=?', (canonical(value).decode(), command))
            db.execute('DROP TRIGGER no_update')  # disposable corruption fixture only
            db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE idempotency_key=?', (canonical(value).decode(), sha(value), command))
        db.commit()
    with pytest.raises(Conflict): service.get(saved['request_id'], token=agent, method='request')


def test_http_exact_request_only_boundary_human_forward_and_private_report(tmp_path):
    store, auth, proposal, service, agent, _, app, _ = setup(tmp_path)
    headers = {'Origin': ORIGIN, 'Authorization': 'Bearer ' + agent, 'Idempotency-Key': 'http_original'}
    payload = {'action': 'submit_goal', 'proposal': proposal, 'expected_revision': 0}
    with TestClient(app, base_url=ORIGIN) as client:
        before = store.audit()
        saved = client.post(BASE + '/agent-requests', headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        value = saved.json(); rid = value['request_id']; url = BASE + '/agent-requests/' + rid
        assert value['status'] == 'AWAITING_HUMAN' and store.audit() == before
        assert client.get(BASE + '/agent-requests', headers=headers).status_code == 403
        assert client.post(BASE + '/commands', headers=headers, json=submit_payload(proposal)).status_code == 403
        assert client.post(url + '/forward', headers=headers, json={'request_hash': value['request_hash'], 'expected_version': 0}).status_code == 403
        read = auth.issue_bearer(Principal('old_reader', 'agent', {'viewer'}, {'project_fixture'}), ttl=50)[0]
        readonly = {**headers, 'Authorization': 'Bearer ' + read}
        assert client.post(BASE + '/agent-requests', headers=readonly, json=payload).status_code == 401
        human = login(client, 'operator')
        assert client.get(BASE + '/agent-requests').json()['items'][0]['request_id'] == rid
        private = client.get(url).json(); assert private['proposal'] == proposal
        bad = {**human, 'X-CSRF-Token': 'incorrect_synthetic_csrf'}
        assert client.post(url + '/forward', headers=bad, json={'request_hash': value['request_hash'], 'expected_version': 0}).status_code == 403
        accepted = client.post(url + '/forward', headers=human, json={'request_hash': value['request_hash'], 'expected_version': 0})
        assert accepted.status_code == 200, accepted.text
        report = client.get(url, headers=headers).json()
        assert report['status'] == 'ADOPTED' and report['result'] == accepted.json()['result']
        assert 'proposal' not in report and agent not in json.dumps(report) and PHRASE not in json.dumps(report)
        other, _ = auth.issue_request_token(Principal('other_agent', 'agent', {'viewer'}, {'project_fixture'}), ttl=50)
        assert client.get(url, headers={'Authorization': 'Bearer ' + other}).status_code == 404
        assert store.version() == 1 and not store.objects('sessions')


def test_identity_copy_fork_and_epoch_replacement_fail_before_locks(tmp_path, monkeypatch):
    store, _, proposal, service, agent, _, _, _ = setup(tmp_path)
    before = store.audit()
    with pytest.raises(PermissionError): submit(copy(service), proposal, agent)
    monkeypatch.setattr(os, 'getpid', lambda: service._pid + 1)
    with pytest.raises(PermissionError): submit(service, proposal, agent)
    monkeypatch.undo()
    with store.connect() as db:
        db.execute("UPDATE observation_meta SET store_epoch='changed_synthetic_epoch' WHERE singleton=1"); db.commit()
    with pytest.raises(Conflict): submit(service, proposal, agent)
    with sqlite3.connect(service.path) as db: assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 0


def test_saved_request_body_key_and_scope_cannot_change(tmp_path):
    store, _, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    altered = deepcopy(proposal); altered['goal_id'] = 'different_goal'
    with pytest.raises(Conflict): submit(service, altered, agent)
    with pytest.raises(Conflict): service.forward(saved['request_id'], request_hash=digest('forged'), expected_version=0, **args)
    assert store.version() == 0


@pytest.mark.parametrize('phase', ['submit', 'forward'])
def test_expiry_during_last_physical_precheck_rolls_back_inbox(tmp_path, monkeypatch, phase):
    store, _, proposal, service, agent, args, _, mono = setup(tmp_path)
    saved = submit(service, proposal, agent) if phase == 'forward' else None
    original = service._pure
    def expire_before_commit():
        original()
        # Only the final physical precheck runs while an actual auth context
        # owns its non-reentrant lock. Earlier DB checks leave clock unchanged.
        if service.auth._lock.locked(): mono[0] = 200
    monkeypatch.setattr(service, '_pure', expire_before_commit)
    with pytest.raises(PermissionError):
        if phase == 'submit': submit(service, proposal, agent)
        else: forward(service, saved, args)
    with sqlite3.connect(service.path) as db:
        rows = db.execute('SELECT body,claim FROM requests').fetchall()
    assert rows == [] if phase == 'submit' else len(rows) == 1 and rows[0][1] is None
    assert store.version() == 0


@pytest.mark.parametrize('damage', ['missing_table', 'foreign_scope', 'oversize_page', 'extra_constraint'])
def test_existing_inbox_damage_is_rejected_without_ddl_or_capacity_reset(tmp_path, damage):
    store, auth, proposal, service, agent, args, _, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    # Preserve a frozen unknown claim without any Core effect.
    with sqlite3.connect(service.path) as db:
        if damage == 'missing_table': db.execute('DROP TABLE requests')
        elif damage == 'foreign_scope': db.execute("UPDATE metadata SET project='foreign'")
        elif damage == 'extra_constraint':
            rows = db.execute('SELECT * FROM requests').fetchall()
            db.execute('DROP TABLE requests')
            db.execute('CREATE TABLE requests (id TEXT PRIMARY KEY, body TEXT NOT NULL COLLATE NOCASE UNIQUE ON CONFLICT REPLACE, claim TEXT)')
            db.executemany('INSERT INTO requests VALUES(?,?,?)', rows)
        else:
            db.execute('PRAGMA page_size=65536'); db.execute('VACUUM')
        db.commit()
        before = db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall()
    cold = Store(store.root)
    draft = DraftService(cold, auth, project_id='project_fixture', data_mode='fixture', origin=ORIGIN)
    with pytest.raises(Conflict): AgentRequestService(draft)
    with sqlite3.connect(service.path) as db:
        assert db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall() == before
        if damage != 'missing_table': assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 1
    assert cold.version() == 0


@pytest.mark.parametrize('raw', ['{"action":"propose_goal_draft","action":"forged"}', '{"number":NaN}', 'x' * (256 * 1024 + 1)])
def test_corrupt_inbox_rows_fail_closed_503_not_user_validation_400(tmp_path, raw):
    _, _, proposal, service, agent, _, app, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    with sqlite3.connect(service.path) as db: db.execute('UPDATE requests SET body=?', (raw,)); db.commit()
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get(BASE + '/agent-requests/' + saved['request_id'], headers={'Authorization': 'Bearer ' + agent})
        assert result.status_code == 503 and result.json()['code'] == 'UNKNOWN_EXECUTION'


def test_real_fork_with_parent_auth_lock_held_rejects_sdk_and_http_without_deadlock(tmp_path):
    import asyncio
    import select
    import signal
    import httpx
    _, auth, proposal, service, agent, _, app, _ = setup(tmp_path)
    saved = submit(service, proposal, agent)
    read, write = os.pipe()
    with auth._lock:
        pid = os.fork()
        if pid == 0:
            os.close(read)
            try:
                for call in (lambda: service.get(saved['request_id'], token=agent, method='request'),
                             lambda: service.list(token=agent)):
                    try: call()
                    except PermissionError: pass
                    else: raise AssertionError('fork accepted')
                async def query():
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                        result = await client.get(BASE + '/agent-requests/' + saved['request_id'], headers={'Authorization': 'Bearer ' + agent})
                        assert result.status_code == 403
                asyncio.run(query())
                os.write(write, b'REJECTED')
            finally:
                os.close(write); os._exit(0)
        os.close(write)
        try:
            if not select.select([read], [], [], 3)[0]:
                os.kill(pid, signal.SIGKILL)
                pytest.fail('fork blocked before original identity rejection')
            assert os.read(read, 32) == b'REJECTED'
        finally:
            os.close(read); os.waitpid(pid, 0)
