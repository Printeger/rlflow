"""Actual installed console; disposable original source fixture only."""
import json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/home/mint/rl_dev/rlflow_standalone')
from tests.test_agent_client import hosted,config
from tests.test_contract_discovery import full_config,REPO
from tests.test_hybrid_control_api import PHRASE
import yaml
root=Path('/tmp/rlflow-cp73-final-wheel-80WomS')
scenario=root/'fixture';scenario.mkdir(mode=0o700)
site=root/'site'
with hosted(scenario) as (store,auth,unused,inbox,credentials):
    target=config(scenario,credentials['RLFLOW_CONTROL_ORIGIN'])
    (target/'.rlflow/project.yaml').write_text(yaml.safe_dump(full_config(target,credentials['RLFLOW_CONTROL_ORIGIN'])))
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(site),**credentials}
    def console(*args):
        result=subprocess.run([str(site/'bin/rlflow'),'client',*args],cwd=target,
            env=env,capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stderr
        assert credentials['RLFLOW_REQUEST_TOKEN'] not in result.stdout+result.stderr
        return result.stdout
    loaded=subprocess.run([sys.executable,'-c','import rlflow.agent_client;print(rlflow.agent_client.__file__)'],
        cwd=target,env=env,capture_output=True,text=True,timeout=10)
    assert loaded.returncode==0 and str(site) in loaded.stdout
    original=store.audit();contract=json.loads(console('describe'))
    assert contract['authority']=='NOT_AUTHORITY' and store.audit()==original
    proposal=json.loads((REPO/'docs/hybrid-v1/examples/goal.fixture.json').read_text())
    proposal.update(schema_version='1.1',allowed_tools=list(contract['tools']),registry_bindings=contract['registry_bindings'],
        evaluation_data={'mode':'EXPLICIT_NONE','datasets':[],'evaluation_rule':{'id':'fixture_rule',
        'version_hash':contract['evaluation_rules']['fixture_rule']['version_hash']}})
    path=target/'proposal.json';path.write_text(json.dumps(proposal))
    saved=json.loads(console('submit-goal','--proposal',str(path),'--key','installed_discovered_original'))
    assert saved['status']=='AWAITING_HUMAN' and store.audit()==original
    assert json.loads(console('status','--request',saved['request_id']))==saved
    human,access=auth.login('operator',PHRASE)
    inbox.forward(saved['request_id'],request_hash=saved['request_hash'],expected_version=0,
        token=human,csrf=access.csrf,origin=credentials['RLFLOW_CONTROL_ORIGIN'])
    report=json.loads(console('report','--request',saved['request_id']))
    assert report['status']=='ADOPTED' and report['result']['result']['state']=='DRAFT' and store.version()==1
    assert not any(store.objects(s) for s in ('tasks','sessions','approvals','jobs'))
    skill=Path(console('skill-path').strip());assert str(site) in str(skill) and 'client describe' in skill.read_text()
    print(json.dumps({'installed_console':True,'outside_checkout_import':True,'complete_original_config':True,
        'describe_source':'original registered contract','discovery_Core_writes':0,'report':'ADOPTED',
        'Core_version':1,'worker_model_approvals':0,'packaged_skill':True,'Goal_completed':False}),flush=True)
