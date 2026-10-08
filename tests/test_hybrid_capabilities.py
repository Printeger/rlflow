import json
from pathlib import Path
from types import SimpleNamespace

from rlflow.capabilities import probe_capabilities, resource_capabilities


def test_missing_runtime_fails_closed(monkeypatch):
    monkeypatch.setattr("rlflow.capabilities.shutil.which", lambda _: None)
    result = probe_capabilities()
    assert not result["compatible"] and not result["native_subagents"]
    assert result["model_access"] == "UNVERIFIED"


def test_probe_never_starts_generation_and_uses_empty_home(monkeypatch):
    calls = []
    monkeypatch.setattr("rlflow.capabilities.shutil.which", lambda _: "/fake/codex")
    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["env"]["HOME"] == kwargs["env"]["CODEX_HOME"]
        assert not (Path(kwargs["env"]["CODEX_HOME"]) / "auth.json").exists()
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="codex-cli test\n")
        if argv[1:] == ["exec", "--help"]:
            return SimpleNamespace(returncode=0, stdout="--json --output-schema resume")
        assert argv[1:3] == ["app-server", "generate-json-schema"]
        root = Path(argv[-1]); root.mkdir()
        (root / "protocol.json").write_text(json.dumps({"type": "object"}))
        return SimpleNamespace(returncode=0, stdout="")
    monkeypatch.setattr("rlflow.capabilities.subprocess.run", run)
    report = probe_capabilities(pinned_version="codex-cli test")
    assert not report["compatible"] and report["protocol_sha256"]
    assert probe_capabilities(pinned_version="codex-cli test", pinned_protocol_sha256=report["protocol_sha256"])["compatible"]
    assert not probe_capabilities(pinned_version="codex-cli test", pinned_protocol_sha256="wrong")["compatible"]
    assert not report["native_subagents"] and not report["hard_token_limit"]
    assert report["interrupt"] == "UNVERIFIED"
    assert len(calls) == 9
    assert not probe_capabilities(pinned_version="old-version")["compatible"]


def test_failed_probe_never_claims_compatibility(monkeypatch):
    monkeypatch.setattr("rlflow.capabilities.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("rlflow.capabilities.subprocess.run",
                        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""))
    assert not probe_capabilities(pinned_version="anything")["compatible"]


def test_cgroup_declarations_are_not_enforcement(tmp_path):
    (tmp_path / "cgroup.controllers").write_text("cpu memory pids")
    report = resource_capabilities(tmp_path)
    assert report["cgroup_version"] == 2
    assert report["resource_enforcement"] == "partial"
    assert not report["strict_execution_admissible"]
