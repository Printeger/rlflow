"""Actual installed-console report with disposable original finite execution."""
import json,subprocess,sys
from pathlib import Path
import pytest,yaml
sys.path.insert(0,'/home/mint/rl_dev/rlflow_standalone')
from tests import test_client_execution_report as target_test
from tests import test_hybrid_finite_host_app as fixture_module
from tests.test_execution_adapter import setup as native_setup
from tests.test_contract_discovery import full_config
root=Path('/tmp/rlflow-cp74-final-wheel-inydRL');site=root/'site'
scenario=root/'fixture';scenario.mkdir(mode=0o700)
real_run=subprocess.run
patch=pytest.MonkeyPatch()
factory=fixture_module.create_finite_host_app
patch.setattr(fixture_module,'create_finite_host_app',lambda *a,**kw:factory(*a,**kw,agent_requests=True))
original_config=target_test.config
def complete_config(parent,origin,**kw):
    path=original_config(parent,origin,**kw)
    data=full_config(path,origin);data['project']['id']=kw['project']
    (path/'.rlflow/project.yaml').write_text(yaml.safe_dump(data))
    return path
patch.setattr(target_test,'config',complete_config)
def installed_run(argv,**kw):
    env={**kw['env'],'PYTHONPATH':str(site)};kw={**kw,'env':env}
    loaded=real_run([sys.executable,'-c','import rlflow.agent_client;print(rlflow.agent_client.__file__)'],**kw)
    assert loaded.returncode==0 and str(site) in loaded.stdout
    return real_run([str(site/'bin/rlflow'),*argv[3:]],**kw)
patch.setattr(target_test,'REAL_RUN',installed_run)
native=native_setup.__wrapped__(scenario,patch)
fixture=fixture_module.application.__wrapped__(scenario,native,patch)
try:
    actual=next(fixture)
    target_test.test_actual_dual_execution_target_client_report_and_original_STOP(actual,scenario,patch)
    skill=site/'rlflow/skills/rlflow/SKILL.md'
    assert 'client execution-report' in skill.read_text()
    print(json.dumps({'installed_console':True,'outside_checkout_import':True,'complete_original_config':True,
        'projects':2,'CPU_raw':384,'engineering_worker_groups':3,'engineering_machine_cases':21,
        'report_Core_writes':0,'review':'NOT_PERFORMED','original_STOP':True,'packaged_skill':True,
        'Goal_completed':False}),flush=True)
finally:
    fixture.close();patch.undo()
