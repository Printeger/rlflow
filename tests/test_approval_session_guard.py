from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading

import pytest

from rlflow.observation import enable
from rlflow.store import Store, Conflict
from rlflow.web_auth import AuthStore, Credential, Principal

PHRASE = 'synthetic isolated guard test passphrase'


def auth_fixture(*, roles=('approver',), projects=('project_fixture',)):
    now = [1.0]
    principal = Principal('fixture_human', 'human', roles, projects)
    auth = AuthStore([Credential.create(principal, PHRASE)], ttl=10, clock=lambda: now[0])
    token, access = auth.login(principal.id, PHRASE)
    return auth, token, access, now


def factory(auth, token, access):
    return lambda: auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf)


def fixture_store(tmp_path):
    store = Store(tmp_path/'state'); enable(store, 'project_fixture', data_mode='fixture')
    return store


def submit(store, guard, *, key='guard_fixture_usage', mutate=None):
    if mutate is None:
        mutate = lambda state: state.setdefault('usage', {}).update(guard_fixture={'input_tokens': 1})
    return store.transact_objects('USAGE_OBSERVED', key, [('usage', 'guard_fixture')], mutate, _authorization=guard)


def test_real_session_guard_and_guard_cannot_be_reused():
    auth, token, access, _ = auth_fixture()
    with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as guard:
        assert guard.check() == access
    with pytest.raises(PermissionError):guard.check()
    auth.revoke(token)
    with pytest.raises(PermissionError):
        with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf):pass


@pytest.mark.parametrize('bad', ['viewer', 'operator', 'cross_project', 'bearer', 'forged_principal',
                                'forged_access', 'unknown_token', 'bad_csrf', 'unicode_csrf', 'unicode_token'])
def test_only_live_scoped_human_approver_session_authenticates(bad):
    roles = (bad,) if bad in ('viewer', 'operator') else ('approver',)
    auth, token, access, _ = auth_fixture(roles=roles)
    project, csrf = 'project_fixture', access.csrf
    if bad == 'cross_project':project = 'other_project'
    elif bad == 'bearer':
        token, _ = auth.issue_bearer(Principal('fixture_reader', 'human', {'viewer'}, {'project_fixture'}), ttl=10)
    elif bad == 'forged_principal':token = access.principal
    elif bad == 'forged_access':token = access
    elif bad == 'unknown_token':token = 'not_a_real_token_at_all_12345'
    elif bad == 'bad_csrf':csrf = 'not_the_actual_csrf_token_12345'
    elif bad == 'unicode_csrf':csrf = '非ASCII' * 8
    elif bad == 'unicode_token':token = '\ud800' * 25
    with pytest.raises(PermissionError) as error:
        with auth.approval_guard(token, project_id=project, csrf=csrf):pass
    assert str(error.value) == 'live scoped human approval session required'


@pytest.mark.parametrize('change', ['revoke', 'expire'])
@pytest.mark.parametrize('lock_kind', ['writer', 'sqlite'])
def test_writer_wait_does_not_block_revoke_and_rechecks_auth_after_wait(tmp_path, monkeypatch, change, lock_kind):
    store = fixture_store(tmp_path); before = store.audit()
    auth, token, access, now = auth_fixture()
    assert auth.resolve(token, 'session') == access  # A stale precheck is not authority.
    attempting_writer = threading.Event()
    original_lock = store.lock
    @contextmanager
    def observed_lock():
        if lock_kind == 'writer':attempting_writer.set()
        with original_lock():
            if lock_kind == 'sqlite':attempting_writer.set()
            yield
    @contextmanager
    def sqlite_lock():
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            yield
            db.commit()
    monkeypatch.setattr(store, 'lock', observed_lock)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with original_lock() if lock_kind == 'writer' else sqlite_lock():
            future = executor.submit(submit, store, factory(auth, token, access))
            assert attempting_writer.wait(2)
            if change == 'revoke':executor.submit(auth.revoke, token).result(timeout=2)
            else:now[0] = 11.0
        with pytest.raises(PermissionError):future.result(timeout=3)
    assert store.audit() == before


def test_concurrent_revoke_linearizes_after_commit_and_guard_covers_commit(tmp_path, monkeypatch):
    store = fixture_store(tmp_path); auth, token, access, _ = auth_fixture()
    inside, release, revoking, revoked = (threading.Event() for _ in range(4))
    exit_versions = []
    @contextmanager
    def held_guard():
        with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as guard:
            yield guard
            exit_versions.append(store.version())  # Must already be durable at guard exit.
    def mutate(state):
        inside.set()
        assert release.wait(3)
        state.setdefault('usage', {})['guard_fixture'] = {'input_tokens': 1}
    def revoke():
        revoking.set(); auth.revoke(token); revoked.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        committing = executor.submit(submit, store, held_guard, mutate=mutate)
        try:
            assert inside.wait(2)
            removing = executor.submit(revoke)
            assert revoking.wait(2)
            assert not revoked.wait(0.05)
        finally:release.set()
        result = committing.result(timeout=3); removing.result(timeout=3)
    assert exit_versions == [result['version']]
    assert auth.resolve(token, 'session') is None
    assert store.get('usage', 'guard_fixture')['input_tokens'] == 1


def test_expiry_after_commit_preparation_rolls_back_fact_projection_and_outbox(tmp_path, monkeypatch):
    store = fixture_store(tmp_path); before = store.audit()
    tables = ('observation_meta', 'observation_events', 'observation_projection', 'observation_counters')
    def public_rows():
        with store.connect() as db:
            return {table:[tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY 1,2')] for table in tables}
    public_before = public_rows()
    auth, token, access, now = auth_fixture()
    original = store._commit
    staged = []
    def expiring_commit(*args, **kwargs):
        staged.append(original(*args, **kwargs)); now[0] = 11.0
        return staged[-1]
    monkeypatch.setattr(store, '_commit', expiring_commit)
    with pytest.raises(PermissionError):submit(store, factory(auth, token, access))
    assert len(staged) == 1 and store.audit() == before
    assert public_rows() == public_before
    assert not store.objects('usage')
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM events WHERE idempotency_key=?', ('guard_fixture_usage',)).fetchone()[0] == 0
    # The old credential still logs in, proving the failed context released its lock.
    assert auth.login('fixture_human', PHRASE) is not None


def test_duplicate_still_requires_fresh_session_and_never_mutates_twice(tmp_path):
    store = fixture_store(tmp_path); auth, token, access, _ = auth_fixture()
    first = submit(store, factory(auth, token, access))
    def forbidden(state):raise AssertionError('duplicate reran mutation')
    again = submit(store, factory(auth, token, access), mutate=forbidden)
    assert again == {'version': first['version'], 'duplicate': True}
    before = store.audit(); auth.revoke(token)
    with pytest.raises(PermissionError):submit(store, factory(auth, token, access), mutate=forbidden)
    assert store.audit() == before


def test_callback_failure_releases_guard_and_rolls_back(tmp_path):
    store = fixture_store(tmp_path); before = store.audit(); auth, token, access, _ = auth_fixture()
    def failing(state):
        state.setdefault('usage', {})['guard_fixture'] = {'input_tokens': 9}
        raise Conflict('fixture callback failure')
    with pytest.raises(Conflict):submit(store, factory(auth, token, access), mutate=failing)
    assert store.audit() == before
    assert submit(store, factory(auth, token, access))['duplicate'] is False


def test_guard_cannot_be_checked_from_another_thread():
    auth, token, access, _ = auth_fixture()
    with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as guard:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with pytest.raises(PermissionError):executor.submit(guard.check).result(timeout=2)
        assert guard.check() == access


def test_configured_missing_guard_fails_closed_without_mutation(tmp_path):
    from contextlib import nullcontext
    store = fixture_store(tmp_path); before = store.audit()
    with pytest.raises(Conflict):submit(store, nullcontext)
    assert store.audit() == before


def test_duplicate_expiry_after_lookup_rejects_without_refreshing_fact(tmp_path, monkeypatch):
    store = fixture_store(tmp_path); auth, token, access, now = auth_fixture()
    submit(store, factory(auth, token, access)); before = store.audit()
    existing = store._existing
    def expire_during_lookup(*args):
        result = existing(*args); now[0] = 11.0
        return result
    monkeypatch.setattr(store, '_existing', expire_during_lookup)
    with pytest.raises(PermissionError):submit(store, factory(auth, token, access))
    assert store.audit() == before


def test_guarded_duplicate_commit_precedes_guard_exit(tmp_path, monkeypatch):
    store = fixture_store(tmp_path); auth, token, access, _ = auth_fixture()
    submit(store, factory(auth, token, access))
    trace = []; connect = store.connect
    def traced_connect():
        db = connect(); db.set_trace_callback(trace.append)
        return db
    monkeypatch.setattr(store, 'connect', traced_connect)
    @contextmanager
    def guard():
        with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as authorized:
            yield authorized
            trace.append('AUTH_GUARD_EXIT')
    assert submit(store, guard)['duplicate'] is True
    assert trace.index('COMMIT') < trace.index('AUTH_GUARD_EXIT')
