"""Finite isolated boundary probes; no model, permission, installer or migration."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rlflow import hybrid_runtime_boundary as boundary


@pytest.fixture
def bound(tmp_path, monkeypatch):
    private = tmp_path / 'protected-installation'
    private.mkdir(mode=0o700)
    scope = tmp_path / 'hybrid-working'
    scope.mkdir(mode=0o700)
    catalog = {'version': 1, 'mode': 'HYBRID_LEGACY_DENIED',
               'scopes': [{'reserved_path': str(scope), 'directory_chain': boundary.directory_chain(scope)}],
               'execution_enabled': False, 'release_enabled': False}
    path = private / 'catalog.json'
    raw = boundary._canonical(catalog)
    path.write_bytes(raw)
    path.chmod(0o600)
    info = path.stat()
    descriptor = {'version': 1, 'mode': 'BOUND_HYBRID_NONEXECUTING', 'catalog_path': str(path),
                  'catalog_sha256': hashlib.sha256(raw).hexdigest(),
                  'catalog_parent_chain': boundary.directory_chain(private),
                  'catalog_identity': [info.st_dev, info.st_ino]}
    monkeypatch.setattr(boundary, '_policy', lambda: descriptor)
    return SimpleNamespace(scope=scope, path=path, descriptor=descriptor, catalog=catalog, private=private)


def test_explicit_unbound_not_missing_policy(monkeypatch):
    monkeypatch.setattr(boundary, '_policy', lambda: {'version': 1, 'mode': 'LEGACY_UNBOUND'})
    boundary.check_legacy()
    boundary.check_legacy('legacy-relative-input')
    boundary.check_cold_entry()


def test_bound_cold_entry_has_no_request_selected_legacy_exception(bound):
    with pytest.raises(boundary.BoundaryDenied, match='raw legacy child'):
        boundary.check_cold_entry()


@pytest.mark.parametrize('suffix', ['', '/child', '/nonexistent/a/b'])
def test_reserved_scope_denies_even_absent_descendant(bound, suffix):
    with pytest.raises(boundary.BoundaryDenied, match='reserved scope'):
        boundary.check_legacy(str(bound.scope) + suffix)


def test_foreign_request_root_cannot_hide_actual_candidate(bound, tmp_path):
    other = tmp_path / 'legacy'
    other.mkdir()
    with pytest.raises(boundary.BoundaryDenied):
        boundary.check_request({'root': str(other), 'candidate': str(bound.scope),
                                'mode': 'LEGACY_UNBOUND', 'permit': True})
    boundary.check_request({'root': str(other), 'candidate': str(other)})


def test_symlink_alias_is_denied(bound, tmp_path):
    alias = tmp_path / 'alias'
    alias.symlink_to(bound.scope, target_is_directory=True)
    with pytest.raises(boundary.BoundaryDenied, match='physical alias'):
        boundary.check_legacy(alias / 'future-file')


@pytest.mark.parametrize('damage', ['missing', 'bytes', 'samebytes-replace', 'symlink', 'mode', 'parent-mode',
                                   'scope-replace', 'parent-replace', 'hardlink'])
def test_bound_damage_denies_even_unrelated_legacy_scope(bound, tmp_path, damage):
    old_raw = bound.path.read_bytes()
    if damage == 'missing':
        bound.path.unlink()
    elif damage == 'bytes':
        bound.path.write_bytes(b'{}')
    elif damage == 'samebytes-replace':
        bound.path.rename(bound.path.with_suffix('.old'))
        bound.path.write_bytes(old_raw)
        bound.path.chmod(0o600)
    elif damage == 'symlink':
        original = bound.path.with_suffix('.old')
        bound.path.rename(original)
        bound.path.symlink_to(original)
    elif damage == 'mode':
        bound.path.chmod(0o644)
    elif damage == 'parent-mode':
        bound.private.chmod(0o755)
    elif damage == 'scope-replace':
        bound.scope.rename(bound.scope.with_name('old-working'))
        bound.scope.mkdir(mode=0o700)
    elif damage == 'parent-replace':
        bound.private.rename(bound.private.with_name('old-installation'))
        bound.private.mkdir(mode=0o700)
        bound.path.write_bytes(old_raw)
        bound.path.chmod(0o600)
    else:
        os.link(bound.path, tmp_path / 'catalog-link')
    with pytest.raises(boundary.BoundaryDenied):
        boundary.check_legacy(tmp_path / 'unrelated-legacy')


@pytest.mark.parametrize('descriptor', [{}, {'version': True, 'mode': 'LEGACY_UNBOUND'},
                                      {'version': 2, 'mode': 'LEGACY_UNBOUND'},
                                      {'version': 1, 'mode': 'LEGACY_UNBOUND', 'permit': True}])
def test_descriptor_closed_schema_fails_closed(monkeypatch, descriptor):
    monkeypatch.setattr(boundary, '_policy', lambda: descriptor)
    with pytest.raises(boundary.BoundaryDenied):
        boundary.check_legacy('/tmp/other')


def test_empty_or_relative_or_oversized_affected_scopes_deny(bound):
    for values in [(), ('relative',), ('/tmp/../etc',)]:
        with pytest.raises(boundary.BoundaryDenied):
            boundary.check_legacy(*values)
    with pytest.raises(boundary.BoundaryDenied):
        boundary.check_request({'write': [str(bound.scope)] * 129})


def test_catalog_parent_rebind_during_relative_open_denies(bound, monkeypatch, tmp_path):
    original_open = os.open
    observed = []
    def racing_open(path, flags, *args, **kwargs):
        if path == 'catalog.json':
            assert kwargs.get('dir_fd') is not None
            observed.append(True)
            bound.private.rename(bound.private.with_name('old-parent'))
            bound.private.mkdir(mode=0o700)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', racing_open)
    with pytest.raises(boundary.BoundaryDenied, match='parent changed'):
        boundary.check_legacy(tmp_path / 'unrelated')
    assert observed == [True]


@pytest.mark.parametrize('field', ['catalog_parent_chain', 'catalog_identity'])
def test_boolean_identity_not_accepted_as_actual_integer(bound, field):
    if field == 'catalog_identity':
        bound.descriptor[field][0] = True
    else:
        bound.descriptor[field][0][0] = True
    with pytest.raises(boundary.BoundaryDenied, match='integer'):
        boundary.check_legacy(bound.scope)


def test_nul_path_rejected_before_filesystem_access(bound):
    with pytest.raises(boundary.BoundaryDenied, match='absolute boundary path'):
        boundary.check_legacy('/tmp/invalid\x00path')


@pytest.mark.parametrize('entry', ['dispatch', 'inner_dispatch', 'schedule', 'worker', 'experiment_submit',
                                  'experiment_worker', 'role', 'resources', 'fake_submit', 'fake_supervise',
                                  'fake_child', 'cpu', 'persistent_cpu', 'codex', 'startup_v1', 'lifeguard'])
def test_protected_legacy_entry_denies_before_side_effects(bound, tmp_path, monkeypatch, entry):
    from rlflow import engine, worker, experiments, lifeguard, resources, jobs, isolation, startup
    def forbidden(*args, **kwargs):
        pytest.fail('legacy entry reached a process/resource side effect')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    request_path = bound.scope / 'request.json'
    request = {'root': str(tmp_path / 'foreign-root'), 'candidate': str(bound.scope),
               'directory': str(bound.scope), 'scratch': str(bound.scope / 'scratch')}
    request_path.write_text(json.dumps(request))
    store = SimpleNamespace(root=bound.scope)
    calls = {
        'dispatch': lambda: engine.dispatch_one(store),
        'inner_dispatch': lambda: engine._dispatch_one(store),
        'schedule': lambda: engine._schedule_pending(store),
        'worker': lambda: worker.run(request_path),
        'experiment_submit': lambda: experiments.submit(store, {'cwd': str(bound.scope)}),
        'experiment_worker': lambda: experiments.worker(request_path),
        'role': lambda: lifeguard.held_role(request_path),
        'resources': lambda: resources.reserve_task(store, {}, 'test'),
        'fake_submit': lambda: jobs.submit(bound.scope, 'test', {}),
        'fake_supervise': lambda: jobs._supervise(bound.scope),
        'fake_child': lambda: jobs._child(bound.scope, -1, -1),
        'cpu': lambda: isolation.cpu_exec('true', bound.scope, tmp_path / 'scratch', 'Engineer'),
        'persistent_cpu': lambda: isolation.persistent_cpu_exec(request, {}),
        'codex': lambda: isolation.codex_command('Engineer', bound.scope, tmp_path / 'scratch',
                                               tmp_path / 'schema', tmp_path / 'output'),
        'startup_v1': lambda: startup.validate_release({**request, 'recovery_protocol': 1}, {}, {}),
        'lifeguard': lambda: lifeguard.start(bound.scope, 'role', {}, tmp_path / 'foreign-root', 1, 'id'),
    }
    with pytest.raises(boundary.BoundaryDenied):
        calls[entry]()
    assert sorted(p.name for p in bound.scope.iterdir()) == ['request.json']


@pytest.mark.parametrize('entry', ['_supervised', '_child', 'fake_child', 'fake_supervise', 'missing_policy', 'fifo_policy'])
def test_actual_cold_file_entry_reads_fixed_policy_not_env_or_request(bound, tmp_path, entry):
    release = tmp_path / 'cold-release'
    release.mkdir(mode=0o700)
    source = Path(boundary.__file__).parent
    for name in ['hybrid_runtime_boundary.py', 'isolation.py', 'tool_journal.py', 'jobs.py']:
        shutil.copyfile(source / name, release / name)
    policy = release / 'runtime_boundary_policy.py'
    policy.write_text('DESCRIPTOR = ' + repr(bound.descriptor) + '\n')
    sentinel = bound.scope / 'should-not-execute'
    cfg = {'read': [str(bound.scope)], 'write': [str(bound.scope)], 'execute': [],
           'guard_directory': str(bound.scope / 'process'), 'command': 'touch ' + str(sentinel),
           'timeout': 1, 'root': str(tmp_path / 'foreign-root'), 'mode': 'LEGACY_UNBOUND'}
    if entry in {'missing_policy', 'fifo_policy'}:
        policy.unlink()
        if entry == 'fifo_policy':
            os.mkfifo(policy, mode=0o600)
        argv = [sys.executable, '-I', str(release / 'isolation.py'), '_child', json.dumps(cfg)]
    elif entry.startswith('fake_'):
        action = '_child' if entry == 'fake_child' else '_supervise'
        argv = [sys.executable, '-I', str(release / 'jobs.py'), action, str(bound.scope)]
        if action == '_child':
            argv += ['-1', '-1']
    else:
        argv = [sys.executable, '-I', str(release / 'isolation.py'), entry, json.dumps(cfg)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10,
                            env={**os.environ, 'RLFLOW_BOUNDARY_MODE': 'LEGACY_UNBOUND',
                                 'RLFLOW_ROOT': str(tmp_path / 'foreign-root')})
    assert result.returncode != 0, result.stdout
    assert 'BoundaryDenied' in result.stderr, result.stderr
    assert not sentinel.exists() and not (bound.scope / 'process').exists()


@pytest.mark.parametrize('entry', ['worker', 'role', 'experiment', 'cpu_child', 'cpu_supervisor',
                                  'fake_child', 'fake_supervisor'])
@pytest.mark.parametrize('request_kind', ['foreign_scope', 'unreadable_fifo'])
def test_actual_bound_cold_entry_denies_forged_foreign_scope_before_request_io(bound, tmp_path, entry, request_kind):
    # Copy a fixture release, NEVER alter the running source checkout policy.
    release = tmp_path / 'guarded-fixture-release'
    source = Path(boundary.__file__).parent
    shutil.copytree(source, release / 'rlflow', ignore=shutil.ignore_patterns('__pycache__'))
    (release / 'rlflow' / 'runtime_boundary_policy.py').write_text('DESCRIPTOR = ' + repr(bound.descriptor) + '\n')
    foreign = tmp_path / 'unbound-looking-root'
    foreign.mkdir()
    request = foreign / 'request.json'
    sentinel = bound.scope / 'payload-must-not-run'
    cfg = {'root': str(foreign), 'directory': str(foreign), 'scratch': str(foreign),
           'candidate': str(foreign), 'read': [str(foreign)], 'write': [str(foreign)], 'execute': [],
           'command': 'touch ' + str(sentinel), 'argv': ['/bin/bash', '-c', 'touch ' + str(sentinel)],
           'timeout': 1, 'recovery_protocol': 1, 'mode': 'LEGACY_UNBOUND',
           'boot_id': 'caller-new-boot', 'lease_valid': True}
    if request_kind == 'unreadable_fifo':
        os.mkfifo(request, mode=0o600)
    else:
        request.write_text(json.dumps(cfg))
    if entry.startswith('cpu_'):
        action = '_child' if entry == 'cpu_child' else '_supervised'
        # Invalid JSON also must not be parsed before BOUND cold rejection.
        argv = [sys.executable, '-I', str(release / 'rlflow' / 'isolation.py'), action,
                'invalid-json' if request_kind == 'unreadable_fifo' else json.dumps(cfg)]
    elif entry.startswith('fake_'):
        action = '_child' if entry == 'fake_child' else '_supervise'
        argv = [sys.executable, '-I', str(release / 'rlflow' / 'jobs.py'), action, str(foreign)]
        if action == '_child':
            argv += ['-1', '-1']
    else:
        module, function = {'worker': ('worker', 'run'), 'role': ('lifeguard', 'held_role'),
                            'experiment': ('experiments', 'worker')}[entry]
        harness = ('import sys;sys.path.insert(0,sys.argv[1]);'
                   f'from rlflow.{module} import {function};{function}(sys.argv[2])')
        argv = [sys.executable, '-I', '-c', harness, str(release), str(request)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0, result.stdout
    assert 'BOUND installation denies raw legacy child execution' in result.stderr, result.stderr
    assert not sentinel.exists()
    assert sorted(p.name for p in foreign.iterdir()) == ['request.json']
