"""Pure CPU derivation and actual refusal; no real model/source qualification."""
import json

import pytest

from rlflow.hybrid_a_workflow_cpu import from_engineer
from rlflow.hybrid_budget_ledger import entry_key
from rlflow.hybrid_goals import digest,head_key
from rlflow.hybrid_local_cpu_profile import MODULES,validate_bound_spec
from rlflow.hybrid_native_model_runtime import NativeCpuInput
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Conflict
from tests.test_hybrid_a_workflow_profile import spec,workflow
from tests.test_hybrid_native_model_result import engineer
from tests.test_hybrid_native_model_usage import publication
from tests.test_hybrid_a_workflow_derivation import original,native_setup,FILES


def material():
    # All parent/source/usage values here are SYNTHETIC format data.
    runtime,result=engineer();pins={name:digest(name) for name in MODULES}
    envelope=spec();envelope.update(candidate_paths=['module/source.py'],cpu_modules_sha256=digest(pins))
    registry,proposal=workflow(envelope);proposal['data_mode']='live'
    proposal['scope']['writable_paths']=['module/']
    binding=runtime['origin']['native_model']
    binding['workflow'].update(profile=envelope['profile'],stage='FIRST_ENGINEER',
        accounting_version='A_REGISTRATION_CEILINGS_V1',envelope_sha256=digest(envelope))
    usage=publication(runtime)
    usage['output_sha256']=runtime['native_model_usage']['output_sha256']
    runtime['native_model_usage']=usage;result['usage_publication_sha256']=digest(usage)
    runtime['native_model_result']=result
    parent={'request':{'project_id':proposal['project_id'],'data_mode':'live',
        'idempotency_key':'synthetic_engineer_stop',
        'goal_ref':head_key(proposal['project_id'],'live',proposal['goal_id']),
        'fixture_runtime':runtime},'decision':'SETTLED','reason':'NATIVE_MODEL_USAGE_SETTLED'}
    return proposal,json.loads(registry._raw),parent,pins


def test_same_envelope_freezes_candidate_checks_and_parent_without_execution(monkeypatch):
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:pytest.fail('pure derivation cannot execute'))
    proposal,config,parent,pins=material()
    binding,value=from_engineer(proposal,config,pins['hybrid_local_runner_service.py'],parent,pins)
    envelope=config['tools']['native_model']['definition']['spec']
    assert value['acceptance']==envelope['cpu_acceptance']
    assert value['seconds']==envelope['cpu_seconds'] and value['limits']==envelope['cpu_limits']
    assert binding['workflow']['parent']=={'key':entry_key(parent['request']),'hash':digest(parent)}
    assert binding['workflow']['candidate_sha256']==parent['request']['fixture_runtime']['native_model_result']['candidate_sha256']
    assert validate_bound_spec(value,binding)==value
    assert binding['command_sha256']==digest(config['commands']['local_cpu'])
    value['acceptance']['stdout']='caller rewrite'
    assert config['tools']['native_model']['definition']['spec']['cpu_acceptance']==envelope['cpu_acceptance']
    _,again=from_engineer(proposal,config,pins['hybrid_local_runner_service.py'],parent,pins)
    assert again['acceptance']['stdout']=='checks passed\n'


@pytest.mark.parametrize('damage',['fixture','unknown','no_usage','no_result','early','role','effort',
    'stage','accounting','envelope','pins','program','goal','project','candidate','checks','paths'])
def test_unknown_changed_or_foreign_parent_cannot_derive_cpu(damage):
    proposal,config,parent,pins=material();runtime=parent['request']['fixture_runtime']
    binding=runtime['origin']['native_model'];program=pins['hybrid_local_runner_service.py']
    if damage=='fixture':parent['request']['data_mode']='fixture'
    elif damage=='unknown':parent['decision']='UNKNOWN'
    elif damage=='no_usage':runtime.pop('native_model_usage')
    elif damage=='no_result':runtime.pop('native_model_result')
    elif damage=='early':runtime['phase']='STOP_REQUESTED'
    elif damage=='role':binding['role']='Evaluator'
    elif damage=='effort':binding['effort']='high'
    elif damage=='stage':binding['workflow']['stage']='CONTINUATION'
    elif damage=='accounting':binding['workflow']['accounting_version']='caller'
    elif damage=='envelope':binding['workflow']['envelope_sha256']=digest('changed')
    elif damage=='pins':pins['hybrid_local_cpu_runtime.py']=digest('changed')
    elif damage=='program':program=digest('changed')
    elif damage=='goal':parent['request']['goal_ref']=digest('changed')
    elif damage=='project':parent['request']['project_id']='another_project'
    elif damage=='candidate':runtime['native_model_result']['files']['module/source.py']='changed'
    elif damage=='checks':config['tools']['local_cpu']['definition']['spec']['checks']='print("override")'
    else:runtime['native_model_result']['allowed_paths'].append('module/extra.py')
    with pytest.raises((Conflict,ProtocolError)):
        from_engineer(proposal,config,program,parent,pins)


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live'}],indirect=True)
def test_actual_no_handoff_settled_free_is_not_known_engineer_cpu_input(original,monkeypatch):
    owner,bundle,token,obs,claim=original
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:pytest.fail('model run remains unauthorized'))
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='cpu_input_negative',
        scenario='native_model',native_model_grant=grant)
    owner.stop_to_terminal(lease)
    attempt=owner._issued(lease)
    assert owner._current(attempt)['status']=='SETTLED' and owner.pool.snapshot()['occupied']==0
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    with pytest.raises(Conflict,match='known Engineer'):
        owner.prepare_workflow_cpu_input(lease)
    with pytest.raises(PermissionError,match='same-lease'):
        owner._issued_workflow_cpu_input(lease,NativeCpuInput(b'{}'))
    assert not owner._native_cpu_inputs
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    assert owner.store.audit()==owner.store.replay()
