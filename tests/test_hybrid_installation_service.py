"""Actual sealed fixture -> immutable core INTENT, not publication or execution."""
from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService
from rlflow.hybrid_runtime_installation import SECTIONS, EVENTS, intent_key
from rlflow.store import Conflict, canonical, sha
from rlflow.snapshot_maintenance import maintain


@pytest.fixture
def owner(tmp_path):
    tmp_path.chmod(0o700)
    builder = FixtureMaterialBuilder(tmp_path, project_id='actual_installation')
    service = FixtureInstallationService(builder)
    return builder, service, builder.prepare()


def test_actual_intent_is_original_sealed_nonexecuting_and_duplicate_is_same_fact(owner):
    builder, service, material = owner
    result = service.persist_intent(material)
    assert result['version'] == 1 and result['duplicate'] is False
    state = builder.store.replay(); key = result['intent_key']
    assert state[SECTIONS[0]][key] == json.loads(material.raw)
    assert state[SECTIONS[0]][key]['execution_enabled'] is False
    assert service.persist_intent(material) == {**result, 'duplicate': True}
    assert builder.store.view()['version'] == 1 and material.stage_path.exists()
    assert not material.release_path.exists()
    with pytest.raises(PermissionError): builder.publish(material)
    with pytest.raises(Conflict): service.persist_ready(material)
    with builder.store.read_connection() as db:
        assert builder.store._installation_summary(db, 1) == ((key, 1), 1)
        assert builder.store._installation_event(db, key)[0] == (
            EVENTS[0], 'hybrid-installer', material.id, 1)


def test_actual_intent_full_audit_snapshot_recover_and_bounded_maintenance(owner):
    builder, service, material = owner
    service.persist_intent(material)
    state = builder.store.replay()
    assert builder.store.audit() == state
    assert builder.store.snapshot()['version'] == 1
    assert builder.store.recover() == state
    assert builder.store.audit() == state
    with builder.store.connect() as db:
        db.execute('UPDATE snapshot_due SET due_version=1 WHERE singleton=1')
    assert maintain(builder.store, seconds=10) is True
    with builder.store.read_connection() as db:
        assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone()) == (0, 1)
    # Recovery does not adopt an execution, controller, working or FD grant.
    assert SECTIONS[1] not in state and not material.release_path.exists()


def test_generic_callbacks_and_foreign_guard_cannot_append_or_delete_private_facts(owner):
    builder, service, material = owner
    value = json.loads(material.raw); key = intent_key(value['request'])
    def mutate(state): state[SECTIONS[0]] = {key: value}
    with pytest.raises(PermissionError):
        builder.store.transact(EVENTS[0], key, mutate)
    with pytest.raises(PermissionError):
        builder.store.transact_objects(EVENTS[0], key, [(SECTIONS[0], key)], mutate)
    class Foreign:
        def check(self): pass
    @contextmanager
    def foreign(): yield Foreign()
    with pytest.raises(PermissionError):
        builder.store.transact_objects('FORGED', key, [(SECTIONS[0], key)], mutate, _authorization=foreign)
    assert builder.store.view()['version'] == 0
    service.persist_intent(material)
    with pytest.raises(PermissionError):
        builder.store.transact_objects('DELETE', 'delete', [(SECTIONS[0], key)],
                                       lambda state: state[SECTIONS[0]].pop(key))
    assert builder.store.view()['version'] == 1


def test_original_material_identity_before_parse_and_owner_cannot_rebind(owner):
    builder, service, material = owner
    with pytest.raises(PermissionError): service.persist_intent(replace(material, raw=b'invalid'))
    with pytest.raises(Conflict, match='cannot be rebound'): FixtureInstallationService(builder)
    assert builder.store.view()['version'] == 0


def test_actual_hash_verification_runs_outside_writer_and_final_fault_rolls_back(owner, monkeypatch):
    builder, service, material = owner
    original = builder.verify; calls = []
    def outside_writer(*args, **kwargs):
        with builder.store.lock(nonblocking=True): calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(builder, 'verify', outside_writer)
    original_commit = builder.store._commit
    def fail_after_append(*args, **kwargs):
        original_commit(*args, **kwargs)
        raise OSError('actual append before COMMIT failure')
    monkeypatch.setattr(builder.store, '_commit', fail_after_append)
    with pytest.raises(OSError): service.persist_intent(material)
    assert calls and builder.store.view()['version'] == 0 and service._active is None
    assert builder.prepare() is material and not material.release_path.exists()
    monkeypatch.setattr(builder.store, '_commit', original_commit)
    assert service.persist_intent(material)['version'] == 1


def test_actual_commit_lost_return_retains_same_original_intent(owner, monkeypatch):
    builder, service, material = owner
    original_connect = builder.store.connect
    class LostReturn:
        def __init__(self, db): self.db = db
        def __getattr__(self, name): return getattr(self.db, name)
        def commit(self):
            self.db.commit()
            raise OSError('durable actual COMMIT lost return')
        def __enter__(self): return self
        def __exit__(self, *args): return self.db.__exit__(*args)
    monkeypatch.setattr(builder.store, 'connect', lambda: LostReturn(original_connect()))
    with pytest.raises(OSError, match='lost return'): service.persist_intent(material)
    assert builder.store.view()['version'] == 1 and material.stage_path.exists()
    assert service._active is None and not material.release_path.exists()
    monkeypatch.setattr(builder.store, 'connect', original_connect)
    assert service.persist_intent(material)['duplicate'] is True
    assert builder.store.view()['version'] == 1


@pytest.mark.parametrize('damage', ['marker', 'fact', 'epoch', 'writer_lock', 'database_parent'])
def test_actual_original_fact_registration_and_physical_identity_corruption_denies(owner, damage):
    builder, service, material = owner
    service.persist_intent(material)
    if damage == 'writer_lock':
        path = builder.store.root / 'runtime/writer.lock'
        path.rename(path.with_name('original.lock')); path.touch()
    elif damage == 'database_parent':
        path = builder.store.db.parent
        path.rename(path.with_name('original-runtime')); path.mkdir(mode=0o700)
    else:
        with builder.store.connect() as db:
            if damage == 'marker': db.execute('DELETE FROM projection WHERE section=? AND object_key=?', (SECTIONS[0], ''))
            elif damage == 'fact': db.execute('DELETE FROM projection WHERE section=?', (SECTIONS[0],))
            else: db.execute("UPDATE observation_meta SET store_epoch='foreign_epoch' WHERE singleton=1")
    with pytest.raises((Conflict, PermissionError, FileNotFoundError)):
        service.persist_intent(material)
    assert material.stage_path.exists() and not material.release_path.exists()


@pytest.mark.parametrize('damage', ['producer', 'inputs', 'extra_put', 'details', 'object_version'])
def test_actual_original_event_full_shape_metadata_and_inputs_cannot_be_forged(owner, damage):
    builder, service, material = owner
    key = service.persist_intent(material)['intent_key']
    with builder.store.connect() as db:
        db.execute('DROP TRIGGER no_update')
        if damage == 'producer': db.execute("UPDATE events SET producer='foreign' WHERE idempotency_key=?", (key,))
        elif damage == 'inputs': db.execute("UPDATE events SET input_versions='{} ' WHERE idempotency_key=?", (key,))
        elif damage == 'object_version': db.execute('UPDATE events SET object_version=99 WHERE idempotency_key=?', (key,))
        else:
            payload = json.loads(db.execute('SELECT payload FROM events WHERE idempotency_key=?', (key,)).fetchone()[0])
            if damage == 'details': payload['details'] = {'forged': True}
            else: payload['put'].append(['historical', 'foreign', {}])
            db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE idempotency_key=?',
                       (canonical(payload).decode(), sha(payload), key))
    with pytest.raises(Conflict): service.persist_intent(material)
    with pytest.raises(Conflict): builder.store.snapshot()
    assert builder.store.view()['version'] == 1 and not material.release_path.exists()


def test_current_core_advance_before_intent_blocks_without_remint(owner):
    builder, service, material = owner
    builder.store.transact_objects('HISTORICAL', 'other', [('historical', 'other')],
                                   lambda state: state['historical'].update(other={}))
    with pytest.raises(Conflict): service.persist_intent(material)
    assert builder.prepare() is material
    assert builder.store.view()['version'] == 1 and not material.release_path.exists()


@pytest.mark.parametrize('damage', ['deleted_domain', 'bad_fact', 'bad_event', 'event_only_tip'])
def test_actual_automatic_maintenance_keeps_due_on_installation_history_corruption(owner, damage):
    builder, service, material = owner
    key = service.persist_intent(material)['intent_key']
    with builder.store.connect() as db:
        db.execute('UPDATE snapshot_due SET due_version=1 WHERE singleton=1')
        if damage == 'deleted_domain': db.execute('DELETE FROM projection WHERE section=?', (SECTIONS[0],))
        elif damage == 'bad_fact':
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?', ('{}', SECTIONS[0], key))
        elif damage == 'bad_event':
            db.execute('DROP TRIGGER no_update')
            db.execute("UPDATE events SET producer='forged' WHERE idempotency_key=?", (key,))
        else:
            # Keep a valid original INTENT event but omit its whole phase from
            # projection: even an empty snapshot must compare real tip/COUNT.
            db.execute('DELETE FROM projection WHERE section IN (?,?)', SECTIONS)
    assert maintain(builder.store, seconds=10) is False
    with builder.store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 0
    assert not material.release_path.exists()


@pytest.mark.parametrize('duplicate', [False, True])
def test_actual_final_source_point_deadline_denies_commit_and_keeps_outbox(owner, monkeypatch, duplicate):
    from rlflow import hybrid_fixture_materials as materials
    builder, service, material = owner
    if duplicate: service.persist_intent(material)
    now = [0.0]; original_point = service._point
    monkeypatch.setattr(materials.time, 'monotonic', lambda: now[0])
    def late_point(*args, **kwargs):
        result = original_point(*args, **kwargs)
        now[0] = 31.0  # AFTER all original source/hash/complete checks.
        return result
    monkeypatch.setattr(service, '_point', late_point)
    with pytest.raises(Conflict, match='cooperative time bound'):
        service.persist_intent(material)
    with builder.store.read_connection() as db:
        version = 1 if duplicate else 0
        assert db.execute('SELECT version FROM projection_meta').fetchone()[0] == version
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == version
        assert db.execute('SELECT source_version FROM observation_meta').fetchone()[0] == version
    assert material.stage_path.exists() and not material.release_path.exists()
    assert service._active is None


def test_actual_intent_then_kernel_publish_then_ready_nonexecuting_full_closure(owner):
    import subprocess
    import sys
    builder, service, material = owner
    with pytest.raises(Conflict): service.publish(material)
    with pytest.raises(Conflict): service.persist_ready(material)
    assert builder.store.view()['version'] == 0 and material.stage_path.exists()
    first = service.persist_intent(material)
    ready = service.publish(material)
    assert ready['version'] == 2 and ready['duplicate'] is False
    assert not material.stage_path.exists() and material.release_path.is_dir()
    state = builder.store.replay()
    assert state[SECTIONS[0]][first['intent_key']] == json.loads(material.raw)
    value = state[SECTIONS[1]][ready['publication_key']]
    assert value['state'] == 'LEGACY_DENIED_READY_NONEXECUTING'
    assert value['execution_enabled'] is value['release_enabled'] is False
    assert service.publish(material) == {**ready, 'duplicate': True}
    assert service.persist_intent(material) == {**first, 'duplicate': True}
    assert builder.prepare() is material
    assert builder.store.audit() == state
    assert builder.store.snapshot()['version'] == 2
    assert builder.store.recover() == state
    with builder.store.connect() as db:
        db.execute('UPDATE snapshot_due SET due_version=2 WHERE singleton=1')
    assert maintain(builder.store, seconds=10) is True
    result = subprocess.run([sys.executable, '-B', '-I', '-c',
                             'import sys; sys.path.insert(0,sys.argv[1]); from rlflow.worker import run; run(sys.argv[2])',
                             str(material.release_path), str(builder.root / 'missing-worker-request')],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'BOUND installation denies raw legacy child execution' in result.stderr
    assert builder.store.view()['version'] == 2
    builder.verify(material)


def test_actual_kernel_no_replace_winner_preserves_existing_destination_and_intent(owner, monkeypatch):
    from rlflow import hybrid_installation_service as module
    builder, service, material = owner; service.persist_intent(material)
    original = module._rename_no_replace; hit = []
    def competitor(parent_fd, old_name, new_name):
        material.release_path.mkdir(mode=0o700)
        (material.release_path / 'original-winner').write_bytes(b'KEEP_WINNER')
        hit.append(True)
        return original(parent_fd, old_name, new_name)
    monkeypatch.setattr(module, '_rename_no_replace', competitor)
    with pytest.raises(FileExistsError): service.publish(material)
    assert hit and (material.release_path / 'original-winner').read_bytes() == b'KEEP_WINNER'
    assert material.stage_path.exists() and builder.store.view()['version'] == 1
    assert service._published is None
    with pytest.raises(Conflict): service.publish(material)


@pytest.mark.parametrize('window', ['rename_before', 'rename_after', 'ready_before_commit', 'ready_after_commit'])
def test_actual_publication_unknown_windows_retain_original_material_and_reconcile(owner, monkeypatch, window):
    from rlflow import hybrid_installation_service as module
    builder, service, material = owner; service.persist_intent(material)
    original_rename = module._rename_no_replace; original_commit = builder.store._commit
    original_connect = builder.store.connect
    if window.startswith('rename'):
        def fail_rename(*args):
            if window == 'rename_after': original_rename(*args)
            raise OSError('original publication lost return')
        monkeypatch.setattr(module, '_rename_no_replace', fail_rename)
    elif window == 'ready_before_commit':
        def fail_ready(*args, **kwargs):
            result = original_commit(*args, **kwargs)
            if args[1] == EVENTS[1]: raise OSError('original READY before COMMIT failure')
            return result
        monkeypatch.setattr(builder.store, '_commit', fail_ready)
    else:
        class LostReadyReturn:
            def __init__(self, db): self.db = db
            def __getattr__(self, name): return getattr(self.db, name)
            def commit(self):
                version = self.db.execute('SELECT version FROM projection_meta').fetchone()[0]
                self.db.commit()
                if version == 2: raise OSError('durable original READY lost return')
            def __enter__(self): return self
            def __exit__(self, *args): return self.db.__exit__(*args)
        monkeypatch.setattr(builder.store, 'connect', lambda: LostReadyReturn(original_connect()))
    with pytest.raises(OSError): service.publish(material)
    expected_version = 2 if window == 'ready_after_commit' else 1
    assert builder.store.view()['version'] == expected_version
    assert builder.prepare() is material and service._active is None
    assert material.stage_path.exists() is (window == 'rename_before')
    assert material.release_path.exists() is (window != 'rename_before')
    monkeypatch.undo()
    result = service.publish(material)
    assert result['version'] == 2 and result['duplicate'] is (window == 'ready_after_commit')
    assert builder.store.view()['version'] == 2
    assert not material.stage_path.exists() and material.release_path.exists()


def test_caller_moving_original_stage_does_not_issue_publication_witness(owner):
    builder, service, material = owner; service.persist_intent(material)
    material.stage_path.rename(material.release_path)
    with pytest.raises(Conflict, match='physically published'): service.persist_ready(material)
    assert builder.store.view()['version'] == 1 and service._published is None
    # Explicit owner reconcile must recheck original core seal and fsync the
    # original parent, not trust the move or disk self-manifest as a grant.
    assert service.publish(material)['version'] == 2


def test_current_version_advance_between_publication_and_ready_keeps_blocked_seal(owner):
    builder, service, material = owner; service.persist_intent(material)
    service._publish(material)
    builder.store.transact_objects('HISTORICAL', 'advance', [('historical', 'advance')],
                                   lambda state: state['historical'].update(advance={}))
    with pytest.raises(Conflict): service.persist_ready(material)
    assert builder.store.view()['version'] == 2
    assert SECTIONS[1] not in builder.store.replay()
    assert material.release_path.exists() and builder.prepare() is material


def test_published_catalog_damage_never_falls_back_or_reissues_ready(owner):
    from pathlib import Path
    builder, service, material = owner; service.persist_intent(material); service._publish(material)
    value = json.loads(material.raw)
    Path(value['expected_seal']['descriptor']['catalog_path']).write_bytes(b'{}')
    with pytest.raises((Conflict, PermissionError)): service.persist_ready(material)
    assert builder.store.view()['version'] == 1 and material.release_path.exists()


@pytest.mark.parametrize('after', [False, True])
def test_actual_publication_parent_fsync_unknown_retains_intent_and_requires_retry(owner, monkeypatch, after):
    from rlflow import hybrid_installation_service as module
    builder, service, material = owner; service.persist_intent(material)
    original = module.os.fsync; parent_identity = material.release_path.parent.stat().st_ino
    def fail_sync(fd):
        if module.os.fstat(fd).st_ino == parent_identity:
            if after: original(fd)
            raise OSError('original parent fsync unknown return')
        return original(fd)
    monkeypatch.setattr(module.os, 'fsync', fail_sync)
    with pytest.raises(OSError, match='fsync unknown'): service.publish(material)
    assert builder.store.view()['version'] == 1 and service._published is None
    assert material.release_path.exists() and not material.stage_path.exists()
    with pytest.raises(Conflict): service.persist_ready(material)
    monkeypatch.undo()
    assert service.publish(material)['version'] == 2


def test_unavailable_actual_no_replace_never_uses_overwriting_fallback(owner, monkeypatch):
    from rlflow import hybrid_installation_service as module
    builder, service, material = owner; service.persist_intent(material)
    monkeypatch.setattr(module.ctypes, 'CDLL', lambda *args, **kwargs: object())
    with pytest.raises(PermissionError, match='no-replace publication unavailable'):
        service.publish(material)
    assert builder.store.view()['version'] == 1 and material.stage_path.exists()
    assert not material.release_path.exists() and service._published is None


@pytest.mark.parametrize('duplicate', [False, True])
def test_actual_ready_final_source_deadline_keeps_original_intent_and_outbox(owner, monkeypatch, duplicate):
    from rlflow import hybrid_fixture_materials as module
    builder, service, material = owner; service.persist_intent(material); service._publish(material)
    if duplicate: service.persist_ready(material)
    now = [0.0]; original = service._point; hits = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def late_ready_point(db, read, version, section, key, expected):
        result = original(db, read, version, section, key, expected)
        if version == 2 and section == SECTIONS[1]:
            hits.append(True); now[0] = 31.0
        return result
    monkeypatch.setattr(service, '_point', late_ready_point)
    with pytest.raises(Conflict, match='cooperative time bound'):
        service.persist_ready(material)
    assert hits
    with builder.store.read_connection() as db:
        version = 2 if duplicate else 1
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == version
        assert db.execute('SELECT version FROM projection_meta').fetchone()[0] == version
        assert db.execute('SELECT source_version FROM observation_meta').fetchone()[0] == version
    assert material.release_path.exists() and not material.stage_path.exists()
