"""Original READY material source context, never writer/runtime authority."""
from dataclasses import replace
import json
import threading

import pytest

from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService
from rlflow.hybrid_reads import ReadBudget
from rlflow.hybrid_runtime_installation import SECTIONS
from rlflow.store import Conflict, canonical


@pytest.fixture
def owner(tmp_path):
    tmp_path.chmod(0o700)
    builder = FixtureMaterialBuilder(tmp_path, project_id='bootstrap_fixture')
    service = FixtureInstallationService(builder); material = builder.prepare()
    service.persist_intent(material); service.publish(material)
    return builder, service, material


def point(service, witness):
    with service.store.read_connection() as db:
        db.execute('BEGIN')
        return service._bootstrap_point(db, witness, ReadBudget(db, 16*1024**2))


def test_original_published_witness_at_later_current_version_and_expires_on_context_exit(owner):
    builder, service, material = owner
    builder.store.transact('HISTORICAL', 'later', lambda state: state['historical'].update(later={'note': 'fixture'}))
    assert builder.store.view()['version'] == 3
    with service._bootstrap_witness(material) as witness:
        refs = point(service, witness)
        assert refs == json.loads(witness.raw) and refs['installation_id'] == material.id
        assert refs['store_epoch'] == builder.store_epoch
        assert witness.inventory.path == material.release_path
        assert builder.store.view()['version'] == 3
    with pytest.raises(PermissionError): point(service, witness)
    assert service._bootstrap_contexts == {}


def test_bootstrap_material_and_context_copy_rejected_before_fields_parse(owner):
    builder, service, material = owner
    with pytest.raises(PermissionError):
        with service._bootstrap_witness(replace(material, raw=b'invalid')): pass
    with service._bootstrap_witness(material) as witness:
        for foreign in (replace(witness, raw=b'invalid'), replace(witness, owner=None), object(), json.loads(witness.raw)):
            with pytest.raises(PermissionError): point(service, foreign)
        refs = point(service, witness)
        assert refs['release_id'] == json.loads(material.raw)['expected_seal']['release_id']


def test_bootstrap_thread_bound_and_cleanup_after_callback_failure(owner):
    builder, service, material = owner; errors = []
    with pytest.raises(RuntimeError, match='body failure'):
        with service._bootstrap_witness(material) as witness:
            def foreign():
                try: point(service, witness)
                except BaseException as error: errors.append(error)
            worker = threading.Thread(target=foreign); worker.start(); worker.join(timeout=5)
            assert not worker.is_alive() and len(errors) == 1 and isinstance(errors[0], PermissionError)
            raise RuntimeError('body failure')
    assert service._bootstrap_contexts == {}
    with pytest.raises(PermissionError): point(service, witness)


def test_bootstrap_hashing_outside_writer_no_new_fact_or_execution_permission(owner, monkeypatch):
    builder, service, material = owner; checks = []; original = builder.verify
    def outside(*args, **kwargs):
        with builder.store.lock(nonblocking=True): checks.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(builder, 'verify', outside)
    before = builder.store.replay()
    with service._bootstrap_witness(material) as witness:
        assert point(service, witness)['project_id'] == builder.project_id
    assert checks and builder.store.replay() == before
    assert all(value['execution_enabled'] is False and value['release_enabled'] is False
               for section in SECTIONS for value in before[section].values())


@pytest.mark.parametrize('phase', ['unpublished', 'intent_only', 'self_moved'])
def test_no_ready_or_unowned_publication_cannot_mint_bootstrap(tmp_path, phase):
    tmp_path.chmod(0o700); builder = FixtureMaterialBuilder(tmp_path, project_id='not_ready')
    service = FixtureInstallationService(builder); material = builder.prepare()
    if phase != 'unpublished': service.persist_intent(material)
    if phase == 'self_moved': material.stage_path.rename(material.release_path)
    with pytest.raises(PermissionError):
        with service._bootstrap_witness(material): pass
    assert service._bootstrap_contexts == {}


@pytest.mark.parametrize('damage', ['missing_ready', 'missing_intent', 'event_payload', 'domain_marker', 'tip_count'])
def test_current_original_source_damage_denies_and_releases_context(owner, damage):
    builder, service, material = owner
    with builder.store.connect() as db:
        if damage in ('missing_ready', 'missing_intent'):
            db.execute('DELETE FROM projection WHERE section=?', (SECTIONS[1 if damage == 'missing_ready' else 0],))
        elif damage == 'event_payload':
            db.execute('DROP TRIGGER no_update')  # Explicit isolated corruption fixture only.
            db.execute('UPDATE events SET payload=? WHERE seq=2', (canonical({'format': 2}).decode(),))
        elif damage == 'domain_marker': db.execute('DELETE FROM projection WHERE section=? AND object_key=?', (SECTIONS[1], ''))
        else:
            # Missing original event cannot be forgiven by the projection alone.
            db.execute('DROP TRIGGER no_delete')  # Never disable production append-only protection.
            db.execute('DELETE FROM events WHERE seq=1')
    with pytest.raises(Conflict):
        with service._bootstrap_witness(material): pass
    assert service._bootstrap_contexts == {}


def test_final_original_point_proof_cannot_extend_cooperative_deadline(owner, monkeypatch):
    builder, service, material = owner
    with service._bootstrap_witness(material) as witness:
        import rlflow.hybrid_fixture_materials as materials
        original = service._state
        def late(*args, **kwargs):
            result = original(*args, **kwargs)
            monkeypatch.setattr(materials.time, 'monotonic', lambda: witness.inventory.deadline + 1)
            return result
        monkeypatch.setattr(service, '_state', late)
        with pytest.raises(Conflict, match='time bound'): point(service, witness)
    assert service._bootstrap_contexts == {}


def test_current_actual_material_damage_after_source_context_denies(owner):
    builder, service, material = owner
    with service._bootstrap_witness(material) as witness:
        # Policy lives under rlflow in the actual controlled release.
        file = material.release_path/'rlflow/runtime_boundary_policy.py'
        file.write_bytes(b'BROKEN')
        with pytest.raises(Conflict): point(service, witness)
    assert service._bootstrap_contexts == {}


def test_bootstrap_point_refuses_duck_budget_and_connection_without_transaction(owner):
    builder, service, material = owner
    with service._bootstrap_witness(material) as witness:
        with builder.store.read_connection() as db:
            with pytest.raises(PermissionError): service._bootstrap_point(db, witness, ReadBudget(db, 16*1024**2))
            db.execute('BEGIN')
            class Duck:
                def __init__(self): self.db = db
            with pytest.raises(PermissionError): service._bootstrap_point(db, witness, Duck())
            assert service._bootstrap_point(db, witness, ReadBudget(db, 16*1024**2)) == json.loads(witness.raw)
