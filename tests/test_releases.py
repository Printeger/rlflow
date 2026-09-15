import json
from pathlib import Path
import pytest
from rlflow import releases,engine
from rlflow.store import Conflict,canonical
from rlflow.verification import code_identity
from test_engine import harness


def report(tmp_path):
    path=tmp_path/'tested.json';path.write_bytes(canonical({'exit_code':0,'code_identity':code_identity(),'isolated_state':True}));return path


def test_freeze_detects_drift_and_keeps_legacy_schemas_replayable(harness,tmp_path):
    target=releases.freeze(tmp_path/'releases')
    assert releases.verify(target)['id']==target.name
    assert releases.freeze(tmp_path/'releases')==target
    (target/'roles/PI.md').write_text('drift')
    with pytest.raises(Conflict):releases.verify(target)


def test_idle_deploy_preserves_pause_enable_and_usage(harness,tmp_path):
    h=harness;before=h.store.replay();releases.deploy(h.store,report(tmp_path));after=h.store.replay()
    assert after['paused']==before['paused'] and after['enabled']==before['enabled']
    assert after['stages']==before['stages']
    assert json.loads((h.store.root/'runtime/current-release.json').read_text())['id'] in after['releases']


def test_active_or_uncertain_session_blocks_release(harness,tmp_path):
    h=harness;engine.dispatch_one(h.store)
    with pytest.raises(Conflict,match='idle'):releases.deploy(h.store,report(tmp_path))
    assert not (h.store.root/'runtime/current-release.json').exists()


def test_frozen_release_preserves_authority_and_default_ledger_paths(tmp_path):
    import subprocess,sys
    target=releases.freeze(tmp_path/'releases')
    script='from rlflow.policy import WORKSPACE,COORDINATION,STOP_PATHS; from rlflow.cli import parser; import json; print(json.dumps([str(WORKSPACE),str(COORDINATION),[str(p) for p in STOP_PATHS],str(parser().parse_args(["status"]).state_dir)]))'
    value=json.loads(subprocess.check_output([sys.executable,'-c',script],cwd=target,text=True))
    assert value[0]==str(Path.home()/'.local/share/rlflow-standalone')
    assert value[1]==str(Path.home()/'.local/share/rlflow-standalone/coordination')
    assert str(Path.home()/'.local/share/rlflow-standalone/coordination/commander/STOP') in value[2]
    assert value[3]==str(Path.home()/'.local/share/rlflow-standalone/coordination/research')


def test_crash_after_release_commit_recovers_pointer_without_budget_change(harness,tmp_path,monkeypatch):
    import subprocess,sys
    h=harness;before=h.store.replay();original=releases.atomic
    def crash(path,data):
        if Path(path).name=='current-release.json':raise OSError('power loss after ledger commit')
        return original(path,data)
    monkeypatch.setattr(releases,'atomic',crash)
    with pytest.raises(OSError):releases.deploy(h.store,report(tmp_path))
    committed=h.store.replay();selected=releases.committed_release(committed)
    assert selected and not (h.store.root/'runtime/current-release.json').exists()
    command=[sys.executable,'-I',str(releases.ROOT/'bootstrap.py'),'--state-dir',str(h.store.root),'status']
    # Bootstrap selects and verifies the committed release even with no pointer export.
    output=subprocess.run(command,capture_output=True,text=True)
    assert output.returncode==0,output.stderr
    monkeypatch.setattr(releases,'atomic',original)
    assert releases.reconcile_pointer(h.store)==selected
    assert h.store.replay()==committed and committed['stages']==before['stages']
    assert json.loads((h.store.root/'runtime/current-release.json').read_text())==selected
