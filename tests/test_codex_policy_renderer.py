"""Unexecuted native bytes: no provider, filesystem probe or execution grant."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rlflow import isolation
from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService


def inputs(**changes):
    value = {'role': 'Engineer', 'candidate': '/fixture/candidate', 'scratch': '/fixture/scratch',
        'schema': '/fixture/control/schema.json', 'output': '/fixture/control/result.json',
        'catalog': {'models': [{'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': 'medium'}],
                              'shell_type': 'unified', 'experimental_supported_tools': ['native']} ]},
        'write_roots': ['/fixture/candidate/module'], 'read_extra': [], 'execute_extra': [],
        'memory_bytes': 128*1024**2, 'model': 'gpt-6.1-sol', 'effort': 'medium', 'command_seconds': 10,
        'codex': '/usr/local/bin/codex', 'python': '/fixture/python', 'isolation_module': '/fixture/code/isolation.py'}
    value.update(changes)
    return value


def config(argv):
    return {argv[i+1].split('=', 1)[0]: json.loads(argv[i+1].split('=', 1)[1])
            for i, value in enumerate(argv) if value == '-c'}


def test_renderer_is_pure_and_detaches_inputs(monkeypatch):
    value = inputs(); original = copy.deepcopy(value)
    def forbidden(*args, **kwargs): raise AssertionError('renderer performed IO/environment lookup')
    class Environment:
        def get(self, *args): forbidden()
        def __getitem__(self, key): forbidden()
        def items(self): forbidden()
    with monkeypatch.context() as patch:
        for name in ('open', 'stat', 'lstat', 'mkdir', 'read', 'write'):
            if hasattr(os, name): patch.setattr(os, name, forbidden)
        for name in ('resolve', 'mkdir', 'read_bytes', 'write_bytes', 'home'):
            patch.setattr(Path, name, forbidden)
        patch.setattr(subprocess, 'run', forbidden); patch.setattr(subprocess, 'Popen', forbidden)
        patch.setattr(os, 'environ', Environment())
        result = isolation._render_codex_policy(**value)
    assert value == original
    argv, models_raw, mcp_raw = result; native = config(argv)
    assert native['sandbox_workspace_write.writable_roots'] == value['write_roots']
    assert json.loads(mcp_raw)['write_roots'] == value['write_roots']
    assert native['mcp_servers.rlflow_cpu.enabled_tools'] == ['cpu_exec']
    assert native['mcp_servers.rlflow_cpu.required'] is True
    assert native['mcp_servers.rlflow_cpu.args'] == ['-I', value['isolation_module'], '_mcp', '/fixture/control/result.json.mcp.json']
    assert all(v is False for k, v in native.items() if k.startswith('features.') and
               k not in ('features.skip_host_skill_discovery', 'features.use_legacy_landlock',
                         'features.tool_registry.turn_metadata_includes_tool_info'))
    model = json.loads(models_raw)['models'][0]
    assert model['shell_type'] == 'disabled' and model['apply_patch_tool_type'] is None
    assert model['experimental_supported_tools'] == [] and model['multi_agent_version'] == 'disabled'
    assert isolation._render_codex_policy(**value) == result
    assert '--ignore-user-config' in argv and '--ignore-rules' in argv and '--ephemeral' in argv


@pytest.mark.parametrize('role', isolation.ROLES)
def test_explicit_empty_writes_never_default_to_whole_candidate(role):
    argv, _, raw = isolation._render_codex_policy(**inputs(role=role, write_roots=[]))
    assert config(argv)['sandbox_workspace_write.writable_roots'] == []
    assert json.loads(raw)['write_roots'] == []


@pytest.mark.parametrize('change', [
    {'write_roots': None}, {'write_roots': ()}, {'write_roots': ['/foreign']},
    {'write_roots': ['/fixture/candidate/module']*2}, {'role': 'Evaluator'},
    {'candidate': 'relative'}, {'candidate': '/fixture/../candidate'}, {'candidate': '/fixture//candidate'},
    {'output': '/fixture/candidate/result'}, {'scratch': '/fixture/candidate/nested'},
    {'scratch': '/fixture'}, {'candidate': '/fixture/control/inside'},
    {'read_extra': [True]}, {'execute_extra': ['/fixture/tool']*129},
    {'memory_bytes': True}, {'command_seconds': False}, {'command_seconds': 3601},
    {'model': 'missing'}, {'effort': 'high'}, {'model': True}, {'effort': True},
    {'catalog': {'models': {}}}, {'catalog': {'models': [{'slug': 'gpt-6.1-sol', 'bad': float('nan')}]}}])
def test_renderer_rejects_invalid_explicit_policy(change):
    with pytest.raises(isolation.IsolationError): isolation._render_codex_policy(**inputs(**change))


def test_legacy_nested_scratch_does_not_expose_control_siblings():
    argv, _, raw = isolation._render_codex_policy(**inputs(scratch='/fixture/control/scratch'))
    native = config(argv); mcp = json.loads(raw)
    assert argv[argv.index('-C') + 1] == '/fixture/control/scratch'
    assert native['sandbox_workspace_write.writable_roots'] == ['/fixture/candidate/module']
    assert mcp['scratch'] == '/fixture/control/scratch'
    assert mcp['write_roots'] == ['/fixture/candidate/module']
    assert mcp['audit'] == '/fixture/control/result.json.commands.jsonl'


@pytest.mark.parametrize('artifact', ['schema.json', 'result.json', 'result.json.models.json',
                                    'result.json.mcp.json', 'result.json.commands.jsonl',
                                    'result.json.commands.jsonl.transport', 'commands', 'tool-registers.jsonl'])
@pytest.mark.parametrize('child', ['', '/nested'])
def test_nested_scratch_cannot_overlap_protected_artifact(artifact, child):
    with pytest.raises(isolation.IsolationError, match='protected control artifact'):
        isolation._render_codex_policy(**inputs(scratch='/fixture/control/' + artifact + child))


def test_protected_artifact_cannot_be_inside_scratch():
    with pytest.raises(isolation.IsolationError):
        isolation._render_codex_policy(**inputs(scratch='/fixture/control/scratch',
                                               schema='/fixture/control/scratch/schema.json'))


@pytest.mark.parametrize('role', ['PI', 'Engineer'])
def test_actual_nested_scratch_cannot_read_or_write_control_sibling(tmp_path, role):
    candidate = tmp_path / 'candidate'; control = tmp_path / 'control'; scratch = control / 'scratch'
    candidate.mkdir(); control.mkdir(); scratch.mkdir()
    protected = control / 'sentinel'; protected.write_text('protected-control')
    isolation._render_codex_policy(**inputs(role=role, candidate=str(candidate), scratch=str(scratch),
        schema=str(control / 'schema.json'), output=str(control / 'result.json'), write_roots=[]))
    result = isolation.cpu_exec(f'printf allowed > {scratch}/own; cat {protected}; printf bad > {protected}',
        candidate, scratch, role, timeout=5, write_roots=[])
    assert result['exit_code'] != 0 and 'protected-control' not in result['stdout']
    assert (scratch / 'own').read_text() == 'allowed' and protected.read_text() == 'protected-control'


def test_actual_tool_registration_path_cannot_be_scratch():
    context = {'schema_version': '1.0', 'session': 'session_one', 'generation': 'generation_one',
               'request_sha256': '1'*64, 'candidate_sha256': '2'*64}
    with pytest.raises(isolation.IsolationError, match='protected control artifact'):
        isolation._render_codex_policy(**inputs(scratch='/fixture/launch/tool-registers.jsonl',
            tool_context=context, tool_launch_directory='/fixture/launch'))


@pytest.mark.parametrize('role,writes', [('Engineer', None), ('Engineer', []), ('Engineer', ['module']), ('Evaluator', None)])
def test_legacy_wrapper_matches_pure_policy_with_explicit_semantics(tmp_path, monkeypatch, role, writes):
    candidate = tmp_path/'candidate'; scratch = tmp_path/'scratch'; control = tmp_path/'control'
    candidate.mkdir(); (candidate/'module').mkdir(); schema = tmp_path/'schema.json'
    raw_writes = None if writes is None else [str(candidate/name) for name in writes]
    calls = []
    def version(argv, **kwargs):
        calls.append((argv, kwargs)); return subprocess.CompletedProcess(argv, 0, isolation.PINNED_VERSION, '')
    monkeypatch.setattr(subprocess, 'run', version)
    catalog = inputs()['catalog']; original = copy.deepcopy(catalog)
    argv, env = isolation.codex_command(role, candidate, scratch, schema, control/'result.json',
        write_roots=raw_writes, _census_catalog=catalog, model='gpt-6.1-sol', memory_bytes=128*1024**2, command_seconds=10)
    explicit = [str(candidate)] if role == 'Engineer' and raw_writes is None else (raw_writes or [])
    expected, models, mcp = isolation._render_codex_policy(role, str(candidate), str(scratch), str(schema),
        str(control/'result.json'), catalog=catalog, write_roots=explicit, read_extra=[], execute_extra=[],
        memory_bytes=128*1024**2, command_seconds=10, model='gpt-6.1-sol', effort='medium',
        codex=isolation.CODEX, python=sys.executable, isolation_module=str(Path(isolation.__file__).resolve()))
    assert calls == [([isolation.CODEX, '--version'], {'capture_output': True, 'text': True, 'timeout': 10})]
    assert argv == expected and catalog == original
    assert (control/'result.json.models.json').read_bytes() == models
    assert (control/'result.json.mcp.json').read_bytes() == mcp
    assert env['CUDA_VISIBLE_DEVICES'] == '' and env['NVIDIA_VISIBLE_DEVICES'] == 'none'


def test_actual_guarded_release_renders_without_legacy_bypass(tmp_path):
    tmp_path.chmod(0o700)
    builder = FixtureMaterialBuilder(tmp_path, project_id='renderer_fixture')
    owner = FixtureInstallationService(builder); material = builder.prepare()
    owner.persist_intent(material); owner.publish(material)
    # The actual freshly published BOUND code is imported in an isolated cold
    # process. Pure rendering succeeds; old codex_command MUST still deny before
    # its attempted version probe or any role path creation. No model called.
    source = ('import sys,json;sys.path.insert(0,' + repr(str(material.release_path)) + ');'
        'from rlflow import isolation;'
        'isolation.subprocess.run=lambda *a,**k: (_ for _ in ()).throw(AssertionError("unexpected invocation"));'
        'value=json.loads(' + repr(json.dumps(inputs(write_roots=[]))) + ');'
        'argv,models,mcp=isolation._render_codex_policy(**value);assert json.loads(mcp)["write_roots"]==[];'
        '\ntry: isolation.codex_command("Engineer",value["candidate"],value["scratch"],value["schema"],value["output"])'
        '\nexcept PermissionError: print("pure policy only; legacy denied; no model calls")'
        '\nelse: raise AssertionError("BOUND legacy bypass")')
    result = subprocess.run([sys.executable, '-B', '-I', '-c', source], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'pure policy only; legacy denied; no model calls'
    builder.verify(material)
