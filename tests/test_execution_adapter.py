"""Non-generating adapter preparation tests; no worker/provider is launched."""
import fcntl
import json
import os
from pathlib import Path
import subprocess

import pytest

from rlflow import isolation
from rlflow.execution_adapter import CodexExecAdapter, PreparationPlan, PreparationBundle, FILES, _digest
from rlflow.hybrid_goals import digest
from rlflow.hybrid_protocol import ProtocolError
from rlflow.hybrid_registry import Registry
from rlflow.store import Conflict, canonical
from tests.test_hybrid_registry import catalog


def native_config():
    config = catalog()
    config['runtime_profile'] = {'adapter': 'codex-exec', 'model': 'gpt-6.1-sol', 'effort': 'medium',
        'codex_version': isolation.PINNED_VERSION, 'native_subagents': False, 'cpu_network': 'none',
        'memory_bytes': 128*1024**2, 'command_seconds': 10}
    return config


def packet(role='Engineer'):
    return {'schema_version': '1.0', 'project_id': 'project_fixture', 'data_mode': 'fixture',
        'store_epoch': 'store_fixture', 'goal_id': 'goal_fixture', 'contract_revision': 1,
        'proposal_hash': digest('declared unverified proposal'), 'approval_key': 'approval_fixture',
        'candidate_snapshot_hash': digest('declared unverified candidate'), 'role': role,
        'context': {'text': 'bounded private task text'}}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # A quoted/unicode path exercises decoded native -c JSON path rewriting.
    root = tmp_path/'private-"反斜\\线'; root.mkdir(mode=0o700)
    candidate = tmp_path/'candidate'; candidate.mkdir()
    writable = candidate/'module'; writable.mkdir()
    cache = tmp_path/'cache'; cache.mkdir(mode=0o700)
    (cache/'models_cache.json').write_bytes(canonical({'models': [{'slug': 'gpt-6.1-sol',
        'supported_reasoning_levels': [{'effort': 'medium'}]}]}))
    monkeypatch.setenv('CODEX_HOME', str(cache))
    monkeypatch.setenv('HTTPS_PROXY', 'PRIVATE_ENV_SENTINEL')
    calls = []
    def version(argv, **kwargs):
        assert argv == [isolation.CODEX, '--version']
        assert kwargs == {'capture_output': True, 'text': True, 'timeout': 10}
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'codex '+isolation.PINNED_VERSION+'\n', '')
    monkeypatch.setattr(isolation.subprocess, 'run', version)
    def forbidden(*args, **kwargs): raise AssertionError('no worker/model process allowed')
    monkeypatch.setattr(isolation.subprocess, 'Popen', forbidden)
    adapter = CodexExecAdapter(Registry(native_config()), root)
    plan = adapter.plan_preparation(packet(), candidate=candidate, write_roots=[writable])
    return adapter, plan, candidate, writable, cache, calls


def test_plan_and_material_only_no_authority_or_auth_environment(setup):
    adapter, plan, candidate, writable, cache, calls = setup
    value = json.loads(plan.raw)
    assert set(value['gates'].values()) == {'UNVERIFIED'}
    assert value['execution_enabled'] is False and calls == []
    assert list(adapter.root.iterdir()) == []
    result = adapter.materialize_preparation(plan)
    assert result['execution_enabled'] is False and len(calls) == 1
    assert adapter.materialize_preparation(plan) == result and len(calls) == 1
    directory = adapter.root/plan.id
    command = json.loads((directory/'command-plan.json').read_bytes())
    assert command['state'] == 'PREPARATION_ONLY' and command['execution_enabled'] is False
    argv = command['argv']; settings = {}
    for index, arg in enumerate(argv):
        if arg == '-c':
            key, encoded = argv[index+1].split('=', 1); settings[key] = json.loads(encoded)
    assert argv[:2] == [isolation.CODEX, 'exec'] and '--json' in argv
    assert argv[argv.index('--output-schema')+1] == str(directory/'result.schema.json')
    assert settings['mcp_servers.rlflow_cpu.args'][-1] == str(directory/'control/result.json.mcp.json')
    assert settings['model_catalog_json'] == str(directory/'control/result.json.models.json')
    assert settings['model_reasoning_effort'] == 'medium'
    assert settings['sandbox_workspace_write.writable_roots'] == [str(writable)]
    for key in ('multi_agent', 'goals', 'shell_tool', 'apply_patch_freeform', 'web_search', 'plugins'):
        assert settings['features.'+key] is False
    mcp = json.loads((directory/'control/result.json.mcp.json').read_bytes())
    assert mcp['candidate'] == str(candidate) and mcp['scratch'] == str(directory/'scratch')
    assert mcp['write_roots'] == [str(writable)] and mcp['memory_bytes'] == 128*1024**2
    model = json.loads((directory/'control/result.json.models.json').read_bytes())['models'][0]
    assert model['slug'] == 'gpt-6.1-sol' and model['shell_type'] == 'disabled'
    assert model['multi_agent_version'] == 'disabled' and model['supports_search_tool'] is False
    for name in (*FILES, 'manifest.json'):
        data = (directory/name).read_bytes()
        assert b'PRIVATE_ENV_SENTINEL' not in data and b'.preparing-' not in data
        assert (directory/name).stat().st_mode & 0o777 == 0o600
    with pytest.raises(PermissionError): adapter.start(plan, approval={'state': 'APPROVED'}, lease={'valid': True})
    assert len(calls) == 1


def test_detached_plan_and_actual_issued_identity(setup):
    adapter, plan, candidate, writable, _, calls = setup
    forged = PreparationPlan(plan.id, plan.raw)
    with pytest.raises(PermissionError): adapter.materialize_preparation(forged)
    incoming = packet(); next_plan = adapter.plan_preparation(incoming, candidate=candidate, write_roots=[writable])
    assert next_plan is plan
    incoming['context']['text'] = 'changed'
    assert json.loads(plan.raw)['packet']['context']['text'] == 'bounded private task text'
    assert adapter.plan_preparation(incoming, candidate=candidate, write_roots=[writable]).id != plan.id
    assert calls == []


@pytest.mark.parametrize('change', ['version', 'adapter', 'model', 'effort', 'delegation', 'network', 'unknown', 'float_limits'])
def test_profile_and_catalog_fail_closed(tmp_path, change):
    root = tmp_path/'private'; root.mkdir(mode=0o700)
    config = native_config(); profile = config['runtime_profile']
    if change == 'version': profile['codex_version'] = 'wrong'
    elif change == 'adapter': profile['adapter'] = 'app-server'
    elif change == 'model': profile['model'] = 'invalid/model'
    elif change == 'effort': profile['effort'] = 'automatic'
    elif change == 'delegation': profile['native_subagents'] = True
    elif change == 'network': profile['cpu_network'] = 'allowlist'
    elif change == 'unknown': profile['arbitrary'] = 'PRIVATE_PROFILE_SENTINEL'
    else: profile['command_seconds'] = 10.0
    with pytest.raises(ProtocolError) as error: CodexExecAdapter(Registry(config), root)
    assert 'PRIVATE_PROFILE_SENTINEL' not in str(error.value)
    assert not list(root.iterdir())


@pytest.mark.parametrize('bad', ['project', 'mode', 'extra', 'nan', 'boolean', 'float', 'oversize'])
def test_packet_fail_closed_before_materialization(setup, bad):
    adapter, _, candidate, writable, _, calls = setup; p = packet()
    if bad == 'project': p['project_id'] = 'other'
    elif bad == 'mode': p['data_mode'] = 'live'
    elif bad == 'extra': p['caller_lease'] = {'valid': True}
    elif bad == 'nan': p['contract_revision'] = float('nan')
    elif bad == 'boolean': p['contract_revision'] = True
    elif bad == 'float': p['contract_revision'] = 1.0
    else: p['context']['text'] = 'x'*300000
    with pytest.raises((Conflict, ProtocolError)):
        adapter.plan_preparation(p, candidate=candidate, write_roots=[writable])
    assert calls == [] and not list(adapter.root.iterdir())


@pytest.mark.parametrize('bad', ['empty_engineer', 'readonly_writes', 'outside', 'overlap', 'symlink', 'file', 'duplicate'])
def test_paths_fail_closed(setup, tmp_path, bad):
    adapter, _, candidate, writable, _, calls = setup; p = packet(); writes = [writable]
    if bad == 'empty_engineer': writes = []
    elif bad == 'readonly_writes': p['role'] = 'Critic'
    elif bad == 'outside': writes = [tmp_path]
    elif bad == 'overlap': candidate = tmp_path; writes = [tmp_path]
    elif bad == 'symlink':
        alias = candidate/'alias'; alias.symlink_to(writable, target_is_directory=True); writes = [alias]
    elif bad == 'file':
        file = candidate/'file'; file.write_text('x'); writes = [file]
    else: writes = [writable, writable]
    with pytest.raises(Conflict): adapter.plan_preparation(p, candidate=candidate, write_roots=writes)
    assert calls == []


def test_readonly_role_has_no_candidate_write_roots(setup):
    adapter, _, candidate, _, _, calls = setup
    plan = adapter.plan_preparation(packet('Critic'), candidate=candidate)
    adapter.materialize_preparation(plan)
    argv = json.loads((adapter.root/plan.id/'command-plan.json').read_bytes())['argv']
    encoded = argv[argv.index('-c', argv.index('-m'))+1]  # config is actually generated, not executed
    assert encoded.startswith('model_reasoning_effort=') and len(calls) == 1
    assert 'sandbox_workspace_write.writable_roots=[]' in argv


@pytest.mark.parametrize('rebind', ['candidate', 'write', 'root'])
def test_directory_rebind_rejected_before_probe(setup, rebind):
    adapter, plan, candidate, writable, _, calls = setup
    path = {'candidate': candidate, 'write': writable, 'root': adapter.root}[rebind]
    path.rename(path.with_name(path.name+'.old')); path.mkdir(mode=0o700)
    with pytest.raises(Conflict): adapter.materialize_preparation(plan)
    assert calls == []


def test_changed_candidate_paths_get_distinct_plan(setup, tmp_path):
    adapter, plan, _, _, _, _ = setup
    other = tmp_path/'other'; other.mkdir(); writable = other/'module'; writable.mkdir()
    assert adapter.plan_preparation(packet(), candidate=other, write_roots=[writable]).id != plan.id


@pytest.mark.parametrize('kind', ['generator', 'too_many'])
def test_write_root_bound_before_path_io(setup, monkeypatch, kind):
    adapter, _, candidate, writable, _, calls = setup
    roots = (p for p in [writable]) if kind == 'generator' else [writable]*129
    original = adapter._path
    def checked(path):
        assert Path(path) == adapter.root, 'write/candidate IO occurred before list bound'
        return original(path)
    monkeypatch.setattr(adapter, '_path', checked)
    with pytest.raises(Conflict, match='bounded concrete'):
        adapter.plan_preparation(packet(), candidate=candidate, write_roots=roots)
    assert calls == []


@pytest.mark.parametrize('tamper', ['artifact', 'rehash', 'manifest', 'fifo', 'symlink', 'hardlink', 'mode', 'control_rebind'])
def test_sealed_material_cannot_be_rehashed_or_replaced(setup, tmp_path, tamper):
    adapter, plan, _, _, _, calls = setup; adapter.materialize_preparation(plan)
    directory = adapter.root/plan.id; target = directory/'packet.json'
    if tamper in ('artifact', 'rehash'):
        target.write_bytes(canonical({'changed': True}))
        if tamper == 'rehash':
            manifest = json.loads((directory/'manifest.json').read_bytes())
            manifest['files']['packet.json'] = _digest(target.read_bytes())
            (directory/'manifest.json').write_bytes(canonical(manifest))
    elif tamper == 'manifest': (directory/'manifest.json').write_bytes(b'{"plan_hash":1,"plan_hash":2}')
    elif tamper == 'fifo': target.unlink(); os.mkfifo(target, mode=0o600)
    elif tamper == 'symlink':
        outside = tmp_path/'outside'; outside.write_text('secret'); target.unlink(); target.symlink_to(outside)
    elif tamper == 'hardlink': os.link(target, tmp_path/'linked')
    elif tamper == 'mode': target.chmod(0o644)
    else:
        control = directory/'control'; control.rename(directory/'old-control'); control.mkdir(mode=0o700)
    with pytest.raises((Conflict, OSError)): adapter.verify_materialization(plan)
    with pytest.raises((Conflict, OSError)): adapter.materialize_preparation(plan)
    assert len(calls) == 1


def test_unknown_existing_directory_not_adopted_after_restart(setup):
    adapter, plan, candidate, writable, _, calls = setup
    adapter.materialize_preparation(plan)
    restarted = CodexExecAdapter(adapter.registry, adapter.root)
    replan = restarted.plan_preparation(packet(), candidate=candidate, write_roots=[writable])
    assert replan.id == plan.id
    with pytest.raises(Conflict, match='no actual seal'): restarted.materialize_preparation(replan)
    assert len(calls) == 1


def test_external_directory_lock_is_nonblocking(setup):
    adapter, plan, _, _, _, calls = setup
    fd = os.open(adapter.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(Conflict, match='busy'): adapter.materialize_preparation(plan)
    finally: os.close(fd)
    assert calls == [] and not list(adapter.root.iterdir())


@pytest.mark.parametrize('failure', ['probe', 'catalog', 'helper', 'budget'])
def test_failed_preparation_cleans_only_own_stage(setup, monkeypatch, failure):
    adapter, plan, _, _, cache, calls = setup
    sentinel = adapter.root/'retained'; sentinel.mkdir(mode=0o700); (sentinel/'data').write_text('retained')
    if failure == 'probe':
        def wrong_version(argv, **kwargs): return subprocess.CompletedProcess(argv, 0, 'codex wrong', '')
        monkeypatch.setattr(isolation.subprocess, 'run', wrong_version)
    elif failure == 'catalog': (cache/'models_cache.json').write_bytes(canonical({'models': []}))
    elif failure == 'helper':
        def fail(*args, **kwargs): raise isolation.IsolationError('failed helper')
        monkeypatch.setattr(isolation, 'codex_command', fail)
    else:
        import rlflow.execution_adapter as module
        monkeypatch.setattr(module, 'MAX_ARTIFACT_BYTES', 10)
    with pytest.raises((Conflict, isolation.IsolationError)): adapter.materialize_preparation(plan)
    assert list(adapter.root.iterdir()) == [sentinel]
    assert (sentinel/'data').read_text() == 'retained'


@pytest.mark.parametrize('bad', ['fifo', 'symlink', 'directory', 'oversize', 'duplicate', 'nan', 'overflow', 'deep'])
def test_public_model_cache_bounded_regular_strict_json(tmp_path, bad):
    path = tmp_path/'models.json'
    if bad == 'fifo': os.mkfifo(path)
    elif bad == 'symlink': path.symlink_to(tmp_path/'missing')
    elif bad == 'directory': path.mkdir()
    elif bad == 'oversize':
        with path.open('wb') as stream: stream.truncate(16*1024**2+1)
    elif bad == 'duplicate': path.write_bytes(b'{"models":[],"models":[]}')
    elif bad == 'nan': path.write_bytes(b'{"models":[],"other":NaN}')
    elif bad == 'overflow': path.write_bytes(b'{"models":[],"other":1e9999}')
    else: path.write_bytes(b'{"models":[],"nested":'+b'['*66+b'0'+b']'*66+b'}')
    with pytest.raises((isolation.IsolationError, OSError)): isolation.read_model_catalog(path)


def test_model_cache_unsupported_effort_does_not_fallback(setup):
    adapter, plan, _, _, cache, calls = setup
    (cache/'models_cache.json').write_bytes(canonical({'models': [{'slug': 'gpt-6.1-sol',
        'supported_reasoning_levels': [{'effort': 'high'}]}]}))
    with pytest.raises(isolation.IsolationError, match='effort'): adapter.materialize_preparation(plan)
    assert len(calls) == 1 and not list(adapter.root.iterdir())


def test_unpublished_bundle_carries_original_expected_seal_before_publish(setup):
    adapter, plan, _, _, _, calls = setup
    bundle = adapter.build_preparation(plan); expected = json.loads(bundle.raw)
    assert bundle.path.is_dir() and not (adapter.root/plan.id).exists()
    assert expected['execution_enabled'] is False and expected['plan_hash'] == _digest(plan.raw)
    assert expected['stage_name'] == bundle.path.name and set(expected['seal']['file_lengths']) == set(FILES)
    for name in FILES:
        assert expected['seal']['file_lengths'][name] == (bundle.path/name).stat().st_size
        assert expected['seal']['manifest']['files'][name] == _digest((bundle.path/name).read_bytes())
    before = adapter.verify_bundle(bundle)
    assert adapter.build_preparation(plan) is bundle and len(calls) == 1
    result = adapter.publish_preparation(bundle)
    assert result == before and not bundle.path.exists() and (adapter.root/plan.id).is_dir()
    assert adapter.publish_preparation(bundle) == result and adapter.verify_bundle(bundle) == result
    assert adapter.materialize_preparation(plan) == result and len(calls) == 1
    assert bundle.raw == canonical(expected)  # original intent bytes survive publication unchanged


def test_foreign_or_forged_bundle_cannot_publish(setup):
    adapter, plan, _, _, _, calls = setup; bundle = adapter.build_preparation(plan)
    forged = PreparationBundle(bundle.plan_id, bundle.raw, bundle.path)
    with pytest.raises(PermissionError): adapter.publish_preparation(forged)
    with pytest.raises(PermissionError): adapter.verify_bundle(forged)
    other = CodexExecAdapter(adapter.registry, adapter.root)
    with pytest.raises(PermissionError): other.publish_preparation(bundle)
    assert len(calls) == 1 and bundle.path.exists() and not (adapter.root/plan.id).exists()


def test_provisional_tamper_does_not_rebuild_or_publish(setup):
    adapter, plan, _, _, _, calls = setup; bundle = adapter.build_preparation(plan)
    (bundle.path/'packet.json').write_bytes(b'{}')
    with pytest.raises(Conflict): adapter.publish_preparation(bundle)
    with pytest.raises(Conflict): adapter.build_preparation(plan)
    assert len(calls) == 1 and bundle.path.exists() and not (adapter.root/plan.id).exists()


def test_publish_does_not_overwrite_destination_that_appeared(setup):
    adapter, plan, _, _, _, calls = setup; bundle = adapter.build_preparation(plan)
    destination = adapter.root/plan.id; destination.mkdir(mode=0o700)
    (destination/'retained').write_text('retained')
    with pytest.raises(Conflict): adapter.publish_preparation(bundle)
    assert (destination/'retained').read_text() == 'retained' and bundle.path.exists() and len(calls) == 1


def test_publication_fsync_failure_preserves_unknown_material_no_auto_retry(setup, monkeypatch):
    adapter, plan, _, _, _, calls = setup; bundle = adapter.build_preparation(plan)
    original = os.fsync; inode = adapter.root.stat().st_ino
    def failing(fd):
        if os.fstat(fd).st_ino == inode: raise OSError('explicit publish fsync failure')
        return original(fd)
    monkeypatch.setattr(os, 'fsync', failing)
    with pytest.raises(OSError): adapter.publish_preparation(bundle)
    destination = adapter.root/plan.id
    original_raw = (destination/'manifest.json').read_bytes()
    assert destination.exists() and plan.id not in adapter._seals and not bundle.path.exists()
    with pytest.raises(Conflict): adapter.materialize_preparation(plan)
    with pytest.raises((Conflict, OSError)): adapter.publish_preparation(bundle)
    assert (destination/'manifest.json').read_bytes() == original_raw and len(calls) == 1


def test_unpublished_final_fsync_failure_does_not_leave_bundle_or_stage(setup, monkeypatch):
    adapter, plan, _, _, _, _ = setup; original = os.fsync; inode = adapter.root.stat().st_ino
    def failing(fd):
        if os.fstat(fd).st_ino == inode: raise OSError('explicit stage durability failure')
        return original(fd)
    monkeypatch.setattr(os, 'fsync', failing)
    with pytest.raises(OSError): adapter.build_preparation(plan)
    assert not adapter._bundles and not adapter._seals and not list(adapter.root.iterdir())
