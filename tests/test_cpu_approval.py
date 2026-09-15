"""Inspect generated config using an artificial catalog; no Codex process or credentials."""
import json
from types import SimpleNamespace
from rlflow import isolation


def test_cpu_exec_is_only_preapproved_tool(tmp_path, monkeypatch):
    home = tmp_path / 'fixture-home'
    home.mkdir()
    (home / 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'gpt-5.6-sol', 'supported_reasoning_levels': [{'effort':'medium'}]}]}))
    monkeypatch.setenv('CODEX_HOME', str(home))
    calls = []
    def version(argv, **kwargs):
        calls.append(argv)
        assert argv == [isolation.CODEX, '--version']
        return SimpleNamespace(returncode=0, stdout='codex-cli ' + isolation.PINNED_VERSION)
    monkeypatch.setattr(isolation.subprocess, 'run', version)
    for role in isolation.ROLES:
        write_root = tmp_path / 'candidate' / 'module'
        argv, env = isolation.codex_command(role, tmp_path / 'candidate', tmp_path / 'scratch',
                                            tmp_path / 'schema', tmp_path / 'control/result',
                                            write_roots=[str(write_root)])
        config = dict(arg.split('=', 1) for i, arg in enumerate(argv) if i and argv[i-1] == '-c')
        config = {k: json.loads(v) for k, v in config.items()}
        assert config['approval_policy'] == 'never'
        assert config['model_reasoning_effort'] == 'medium'
        assert argv[argv.index('-m')+1] == 'gpt-5.6-sol'
        assert config['mcp_servers.rlflow_cpu.enabled_tools'] == ['cpu_exec']
        overrides = {k: v for k, v in config.items() if k.endswith('.approval_mode')}
        assert overrides == {'mcp_servers.rlflow_cpu.tools.cpu_exec.approval_mode': 'approve'}
        assert argv[argv.index('--sandbox')+1] == 'workspace-write'
        assert config['sandbox_workspace_write.writable_roots'] == ([str(write_root)] if role == 'Engineer' else [])
        assert config['sandbox_workspace_write.exclude_slash_tmp'] is True
        assert config['sandbox_workspace_write.exclude_tmpdir_env_var'] is True
        assert config['features.shell_tool'] is False
        assert config['features.multi_agent'] is False
        mcp = json.loads((tmp_path / 'control/result.mcp.json').read_text())
        assert mcp['role'] == role
        assert mcp['write_roots'] == [str(write_root)]
        assert env['CUDA_VISIBLE_DEVICES'] == ''
    assert len(calls) == len(isolation.ROLES)
