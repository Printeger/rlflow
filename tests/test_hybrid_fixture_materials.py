"""Actual fresh fixture material, NEVER a published installation or worker grant."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder, _read_bounded, _inventory
from rlflow.hybrid_runtime_boundary import policy_source, directory_chain
from rlflow.store import Conflict


@pytest.fixture
def prepared(tmp_path):
    tmp_path.chmod(0o700)
    builder = FixtureMaterialBuilder(tmp_path, project_id='fixture_installation_test')
    material = builder.prepare()
    return builder, material


def test_actual_fresh_material_closes_catalog_policy_and_release_seal(prepared):
    builder, material = prepared
    value = builder.verify(material)
    assert builder.store.view()['version'] == 0
    assert value['request']['data_mode'] == 'fixture'
    assert value['execution_enabled'] is False and value['release_enabled'] is False
    seal = value['expected_seal']; descriptor = seal['descriptor']
    raw = (material.stage_path / 'rlflow/runtime_boundary_policy.py').read_bytes()
    assert raw == policy_source(descriptor)
    assert hashlib.sha256(raw).hexdigest() == seal['release_manifest']['rlflow/runtime_boundary_policy.py']
    assert not material.release_path.exists()
    assert builder.prepare() is material  # No remint, no new namespace/epoch.
    with pytest.raises(PermissionError, match='core installation INTENT'):
        builder.publish(material)
    assert builder.store.view()['version'] == 0 and not material.release_path.exists()


def test_copied_foreign_or_mutated_material_is_not_an_original_capability(prepared):
    builder, material = prepared
    with pytest.raises(PermissionError): builder.verify(replace(material))
    original = material.raw
    object.__setattr__(material, 'raw', b'not original issued bytes')
    with pytest.raises(Conflict, match='fields differ'): builder.verify(material)
    object.__setattr__(material, 'raw', original)
    builder.verify(material)


@pytest.mark.parametrize('damage', ['policy', 'catalog', 'extra_file', 'root_file', 'root_directory',
                                  'cache', 'extra_directory', 'oversize_file', 'destination', 'namespace'])
def test_actual_stage_corruption_or_rebound_scope_denies_without_publication(prepared, damage):
    builder, material = prepared
    if damage == 'policy':
        (material.stage_path / 'rlflow/runtime_boundary_policy.py').write_text("DESCRIPTOR = {'version':1,'mode':'LEGACY_UNBOUND'}\n")
    elif damage == 'catalog':
        value = json.loads(material.raw)
        Path(value['expected_seal']['descriptor']['catalog_path']).write_bytes(b'{}')
    elif damage == 'extra_file':
        (material.stage_path / 'rlflow/extra_unsealed.py').write_text('raise RuntimeError()')
    elif damage == 'root_file':
        (material.stage_path / 'unsealed.py').write_text('raise RuntimeError()')
    elif damage == 'root_directory':
        (material.stage_path / 'extra').mkdir(mode=0o700)
    elif damage == 'cache':
        (material.stage_path / 'rlflow/__pycache__').mkdir(mode=0o700)
    elif damage == 'extra_directory':
        (material.stage_path / 'rlflow/extra').mkdir(mode=0o700)
    elif damage == 'oversize_file':
        path = material.stage_path / 'rlflow/runtime_boundary_policy.py'
        with path.open('wb') as stream: stream.truncate(16 * 1024**2 + 1)
    elif damage == 'destination':
        material.release_path.mkdir()
    else:
        path = builder._roots['working']; path.rename(path.with_name('original-working')); path.mkdir(mode=0o700)
    with pytest.raises((Conflict, PermissionError)):
        builder.verify(material)
    assert builder.store.view()['version'] == 0
    assert material.stage_path.exists()


def test_actual_generated_bound_cold_entry_cannot_execute_before_intent(prepared):
    builder, material = prepared
    sentinel = builder._roots['working'] / 'must-not-execute'
    cfg = {'root': '/tmp/foreign-legacy', 'read': ['/tmp/foreign-legacy'],
           'write': ['/tmp/foreign-legacy'], 'execute': [], 'command': 'touch ' + str(sentinel), 'timeout': 1}
    result = subprocess.run([sys.executable, '-B', '-I', str(material.stage_path / 'rlflow/isolation.py'),
                             '_child', json.dumps(cfg)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'BOUND installation denies raw legacy child execution' in result.stderr
    assert not sentinel.exists() and builder.store.view()['version'] == 0
    builder.verify(material)


def test_failed_preparation_retains_single_original_blocked_attempt(tmp_path, monkeypatch):
    from rlflow import hybrid_fixture_materials as module
    tmp_path.chmod(0o700)
    builder = FixtureMaterialBuilder(tmp_path, project_id='p')
    def failure(*args, **kwargs): raise OSError('injected original material write fault')
    monkeypatch.setattr(module, '_write_new', failure)
    with pytest.raises(OSError): builder.prepare()
    original = builder._attempt
    with pytest.raises(Conflict, match='retained blocked attempt'): builder.prepare()
    assert builder._attempt is original and not builder._issued
    assert builder.store.view()['version'] == 0


def test_bounded_nonblocking_read_denies_fifo_without_opening_a_payload(tmp_path):
    fifo = tmp_path / 'fifo'; os.mkfifo(fifo)
    with pytest.raises(Conflict, match='regular fixture file'):
        _read_bounded(fifo, 16 * 1024**2)


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_actual_source_swap_read_restore_cannot_seal_foreign_bytes(tmp_path, monkeypatch, kind):
    from rlflow import hybrid_fixture_materials as module
    tmp_path.chmod(0o700)
    builder = FixtureMaterialBuilder(tmp_path, project_id='source_swap')
    source = tmp_path / 'trusted-template'; source.mkdir(mode=0o700)
    for name in module._FOLDERS:
        shutil.copytree(builder._source / name, source / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in module._TOP_FILES:
        shutil.copyfile(builder._source / name, source / name)
    builder._source = source; builder._source_chain = directory_chain(source)
    target = source / 'rlflow/hybrid_runtime_boundary.py'
    original_bytes = target.read_bytes(); original_read = module._read_bounded
    hit = []
    def swapped_read(path, *args, **kwargs):
        if Path(path) != target or hit:
            return original_read(path, *args, **kwargs)
        hit.append(True)
        original = target if kind == 'file' else target.parent
        saved = original.with_name(original.name + '-original')
        original.rename(saved)
        if kind == 'file': original.write_bytes(b'FOREIGN_READ_RESTORE_BYTES')
        else:
            original.mkdir(mode=0o700)
            (original / target.name).write_bytes(b'FOREIGN_READ_RESTORE_BYTES')
        try:
            return original_read(path, *args, **kwargs)
        finally:
            # Test-generated private fixture only; never the source checkout.
            if kind == 'file': original.unlink()
            else:
                (original / target.name).unlink(); original.rmdir()
            saved.rename(original)
    monkeypatch.setattr(module, '_read_bounded', swapped_read)
    with pytest.raises(Conflict, match='original .*fixture'):
        builder.prepare()
    assert hit and target.read_bytes() == original_bytes
    assert builder.store.view()['version'] == 0 and not builder._issued
    with pytest.raises(Conflict, match='retained blocked attempt'): builder.prepare()


def test_actual_sealed_inventory_file_count_is_bounded(prepared):
    builder, material = prepared
    for number in range(1026):
        path = material.stage_path / 'rlflow' / ('extra-' + str(number))
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    with pytest.raises(Conflict, match='file count exceeds bound'):
        builder.verify(material)
    assert builder.store.view()['version'] == 0


@pytest.mark.parametrize('damage', ['symlink', 'fifo', 'public_file'])
def test_closed_inventory_rejects_actual_unsealed_entry_types(prepared, damage):
    builder, material = prepared
    path = material.stage_path / 'rlflow/hybrid_runtime_boundary.py'
    if damage == 'public_file': path.chmod(0o644)
    else:
        path.unlink()
        if damage == 'symlink': path.symlink_to('/dev/null')
        else: os.mkfifo(path, 0o600)
    with pytest.raises(Conflict): builder.verify(material)
    assert builder.store.view()['version'] == 0


def test_prepare_final_sync_deadline_denies_retaining_unpublished_attempt(tmp_path, monkeypatch):
    from rlflow import hybrid_fixture_materials as module
    tmp_path.chmod(0o700); builder = FixtureMaterialBuilder(tmp_path, project_id='deadline')
    now = [0.0]; original = module._sync_directory
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def late_sync(path):
        original(path)
        if Path(path) == builder.root: now[0] = 31.0
    monkeypatch.setattr(module, '_sync_directory', late_sync)
    with pytest.raises(Conflict, match='cooperative time bound'): builder.prepare()
    assert not builder._issued and builder._attempt
    with pytest.raises(Conflict, match='retained blocked attempt'): builder.prepare()
    assert builder.store.view()['version'] == 0


@pytest.mark.parametrize('late_point', ['catalog', 'final_owner'])
def test_verify_final_deadline_after_catalog_and_owner_checks(prepared, monkeypatch, late_point):
    from rlflow import hybrid_fixture_materials as module
    builder, material = prepared; now = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    if late_point == 'catalog':
        original = module._catalog
        def late_catalog(value):
            result = original(value); now[0] = 31.0; return result
        monkeypatch.setattr(module, '_catalog', late_catalog)
    else:
        original = builder._check; calls = []
        def late_check():
            original(); calls.append(True)
            if len(calls) == 2: now[0] = 31.0
        monkeypatch.setattr(builder, '_check', late_check)
    with pytest.raises(Conflict, match='cooperative time bound'): builder.verify(material)
    assert builder.store.view()['version'] == 0 and not material.release_path.exists()


def test_inventory_deadline_is_checked_during_enumeration(prepared, monkeypatch):
    from rlflow import hybrid_fixture_materials as module
    _, material = prepared; ticks = iter([0.0, 0.0, 31.0])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(ticks, 31.0))
    with pytest.raises(Conflict, match='cooperative time bound'):
        with _inventory(material.stage_path, closed=True, deadline=30): pass


def test_completed_prepare_rechecks_original_material_instead_of_hiding_damage(prepared):
    builder, material = prepared
    (material.stage_path / 'extra.py').write_bytes(b'UNSEALED')
    with pytest.raises(Conflict): builder.prepare()
    assert builder._attempt['material'] is material
    assert not material.release_path.exists() and builder.store.view()['version'] == 0
