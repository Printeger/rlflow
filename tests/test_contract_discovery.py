"""Actual static project metadata → original discovery → nonexecuting DRAFT."""
from copy import deepcopy
import json
from pathlib import Path
import yaml
import pytest
from fastapi.testclient import TestClient

from rlflow.agent_client import AgentClient, ClientError
from rlflow.hybrid_agent_requests import AgentRequestService
from rlflow.hybrid_contract_discovery import validate_public
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_protocol import validate_schema
from rlflow.hybrid_goals import SECTIONS
from rlflow.web_api import create_app
from rlflow.web_auth import Principal
from tests.test_agent_client import hosted,config
from tests.test_hybrid_control_api import setup as core_setup,ORIGIN,PHRASE,BASE
from tests.test_hybrid_registry import catalog

REPO=Path(__file__).resolve().parents[1]


def full_config(target,origin):
    data=yaml.safe_load((REPO/'docs/hybrid-v1/examples/project.example.yaml').read_text())
    data['project'].update(root=str(target),state_dir=str(target.parent/'protected-state'),
        data_roots=[str(target.parent/'readonly-data')],artifact_root=str(target.parent/'artifacts'))
    data['runtime']['pinned_version']='fixture-version-advisory-only'
    data['dashboard']['port']=int(origin.rsplit(':',1)[1])
    return data


def test_actual_full_configuration_discovery_builds_original_proposal_and_DRAFT(tmp_path):
    with hosted(tmp_path) as (store,auth,unused,inbox,env):
        target=config(tmp_path,env['RLFLOW_CONTROL_ORIGIN'])
        (target/'.rlflow/project.yaml').write_text(yaml.safe_dump(full_config(target,env['RLFLOW_CONTROL_ORIGIN'])))
        client=AgentClient(cwd=target,environ=env)
        before=store.audit();discovered=client.describe()
        validate_public(discovered,'project_fixture','fixture')
        assert discovered['authority']=='NOT_AUTHORITY' and not discovered['execution_enabled']
        assert store.audit()==before
        with inbox._db() as db:assert db.execute('SELECT count(*) FROM requests').fetchone()[0]==0
        # User-authored requirements + actual discovered registrations, not a
        # test helper's precomputed bindings or server-generated authorization.
        proposal=json.loads((REPO/'docs/hybrid-v1/examples/goal.fixture.json').read_text())
        proposal.update(schema_version='1.1',allowed_tools=list(discovered['tools']),
            registry_bindings=discovered['registry_bindings'],evaluation_data={
                'mode':'EXPLICIT_NONE','datasets':[],'evaluation_rule':{
                    'id':'fixture_rule','version_hash':discovered['evaluation_rules']['fixture_rule']['version_hash']}})
        validate_schema(discovered['goal_proposal_schema'],proposal)
        assert store._hybrid_registry.resolve(proposal)['state']=='NOT_EXECUTABLE'
        saved=client.submit_goal(proposal,key='discovered_original_goal')
        assert saved['status']=='AWAITING_HUMAN' and store.audit()==before
        token,access=auth.login('operator',PHRASE)
        accepted=inbox.forward(saved['request_id'],request_hash=saved['request_hash'],expected_version=store.version(),
            token=token,csrf=access.csrf,origin=env['RLFLOW_CONTROL_ORIGIN'])
        assert accepted['status']=='ADOPTED' and client.get_report(saved['request_id'])['status']=='ADOPTED'
        assert store.version()==1 and len(store.objects(SECTIONS[0]))==1
        assert not any(store.objects(s) for s in ('tasks','sessions','approvals','jobs'))
        assert sorted(p.name for p in target.iterdir())==['.rlflow']
    print('actual_full_config_discovery_DRAFT',{'source':'original registered contract','Core_version':1,
        'discovery_Core_writes':0,'workers':0,'approvals':0},flush=True)


@pytest.mark.parametrize('mutation',['duplicate','unknown','credential','origin','root','state','mode','alias','depth'])
def test_invalid_complete_metadata_has_no_HTTP_or_Store(tmp_path,monkeypatch,mutation):
    target=config(tmp_path,ORIGIN);data=full_config(target,ORIGIN)
    if mutation=='unknown':data['runtime']['unrecognized']=True
    elif mutation=='credential':data['commands']['fixture_test']['parameters']['api_key']='never_sent_fixture_secret'
    elif mutation=='origin':data['dashboard']['port']=8766
    elif mutation=='root':data['project']['root']='SET_ME_ABSOLUTE_PROJECT_ROOT'
    elif mutation=='state':data['project']['state_dir']=str(target/'state')
    elif mutation=='mode':data['data_mode']='unrecognized'
    elif mutation=='depth':
        value={}
        for _ in range(40):value={'nested':value}
        data['commands']['fixture_test']['parameters']=value
    raw=yaml.safe_dump(data)
    if mutation=='duplicate':raw=raw.replace('  auth_required: true','  auth_required: true\n  auth_required: false')
    if mutation=='alias':raw=raw.replace('fast_reader: null','fast_reader: &credential null').replace('standard_worker: null','standard_worker: *credential')
    (target/'.rlflow/project.yaml').write_text(raw)
    def forbidden(*a,**kw):pytest.fail('invalid metadata performed external action')
    monkeypatch.setattr('rlflow.store.Store.__init__',forbidden)
    monkeypatch.setattr('socket.create_connection',forbidden)
    with pytest.raises(ClientError):AgentClient(cwd=target,environ={
        'RLFLOW_CONTROL_ORIGIN':ORIGIN,'RLFLOW_REQUEST_TOKEN':'never_sent_fixture_request_token'})
    assert not (target/'state').exists()


def discovery_setup(tmp_path,configuration=None):
    store,auth,proposal,unused,pair,projects,mono=core_setup(tmp_path,config=configuration)
    inbox=AgentRequestService(pair.drafts)
    agent,_=auth.issue_request_token(Principal('discovery_agent','agent',{'viewer'},{'project_fixture'}),ttl=50)
    app=create_app(projects,auth,origin=ORIGIN,control_services={'project_fixture':pair},
        agent_request_services={'project_fixture':inbox})
    return store,auth,pair,inbox,agent,app,mono


def test_discovery_raw_rebinding_refused_and_returned_schema_detached(tmp_path):
    from rlflow.hybrid_contract_discovery import ContractDiscovery
    from rlflow.store import Conflict
    store,auth,pair,inbox,agent,app,mono=discovery_setup(tmp_path)
    discovery=ContractDiscovery(inbox,pair)
    first=discovery.read(token=agent,method='request')
    original=deepcopy(first)
    first['goal_proposal_schema']['properties']['project_id']['type']='integer'
    assert discovery.read(token=agent,method='request')==original
    changed=json.loads(discovery.raw)
    changed['tools']['cpu_exec']['adapter']='other_adapter'
    discovery.raw=json.dumps(changed).encode()
    with pytest.raises(Conflict):discovery.read(token=agent,method='request')


def test_full_mode_mismatch_rejected_before_HTTP(tmp_path,monkeypatch):
    target=config(tmp_path,ORIGIN)
    metadata=full_config(target,ORIGIN);metadata['data_mode']='live'
    (target/'.rlflow/project.yaml').write_text(yaml.safe_dump(metadata))
    client=AgentClient(cwd=target,environ={'RLFLOW_CONTROL_ORIGIN':ORIGIN,
        'RLFLOW_REQUEST_TOKEN':'unused_fixture_token_123456789'})
    def forbidden(*a,**kw):pytest.fail('mode mismatch sent HTTP')
    monkeypatch.setattr(client,'_call',forbidden)
    with pytest.raises(ClientError):client.submit_goal({'project_id':'project_fixture',
        'contract_version':1,'data_mode':'fixture'},key='mode_mismatch')
    with pytest.raises(ClientError):client.request_finite_stop({},key='mode_mismatch')


def test_projection_excludes_opaque_secrets_and_inbox_health_is_not_discovery_authority(tmp_path):
    original=catalog();secret='opaque_fixture_never_disclosed'
    for section in ('runtime_profile','resource_profile'):
        original[section]['private_value']=secret
    original['tools']['cpu_exec']['definition']['private_value']=secret
    original['evaluation_rules']['fixture_rule']['definition']['private_value']=secret
    original['project_policy']['configuration']['private_value']=secret
    original['commands']['fixture_test']['argv'].append(secret)
    original['datasets']['fixture_data']['source']['reference']=secret
    store,auth,pair,inbox,agent,app,mono=discovery_setup(tmp_path,original)
    before=store.audit()
    with TestClient(app,base_url=ORIGIN) as client:
        # Only this disposable inbox file is unavailable. The original
        # Registry/Store is still valid; metadata read must not need inbox IO.
        inbox.path.rename(inbox.path.with_suffix('.held'))
        response=client.get(BASE+'/proposal-contract',headers={'Authorization':'Bearer '+agent})
        assert response.status_code==200,response.text
        value=response.json();validate_public(value,'project_fixture')
        assert secret not in response.text
        assert value['config_hash']==pair.approvals.registry.config_hash
        assert value['registry_bindings']==pair.approvals.registry.bindings
        assert store.audit()==before


@pytest.mark.parametrize('unsafe',[{'$ref':'https://fixture.invalid/not_fetched'},
    {'type':'object','description':'never_disclosed_fixture_secret'},
    {'type':'string','default':'never_disclosed_fixture_secret'}])
def test_opaque_parameter_schema_refused_without_fetch_or_disclosure(tmp_path,monkeypatch,unsafe):
    configuration=catalog();configuration['commands']['fixture_test']['parameter_schema']=unsafe
    store,auth,pair,inbox,agent,app,mono=discovery_setup(tmp_path,configuration)
    with TestClient(app,base_url=ORIGIN) as client:
        def forbidden(*a,**kw):pytest.fail('opaque schema caused network access')
        monkeypatch.setattr('socket.create_connection',forbidden)
        response=client.get(BASE+'/proposal-contract',headers={'Authorization':'Bearer '+agent})
        assert response.status_code==409 and response.json()['code']=='UNSUPPORTED_CAPABILITY'
        assert 'never_disclosed_fixture_secret' not in response.text and 'fixture.invalid' not in response.text


@pytest.mark.parametrize('late',['revocation','registry','epoch'])
def test_discovery_checks_original_source_and_permission_after_read(tmp_path,monkeypatch,late):
    import rlflow.hybrid_contract_discovery as discovery
    store,auth,pair,inbox,agent,app,mono=discovery_setup(tmp_path)
    original=discovery.schemas;once=[False]
    def changed():
        if not once[0]:
            once[0]=True
            if late=='revocation':auth.revoke(agent)
            elif late=='registry':pair.approvals.registry=Registry(catalog())
            else:
                with store.connect() as db:
                    db.execute('UPDATE observation_meta SET store_epoch=? WHERE singleton=1',('store_'+'f'*32,));db.commit()
        return original()
    with TestClient(app,base_url=ORIGIN) as client:
        monkeypatch.setattr(discovery,'schemas',changed)
        response=client.get(BASE+'/proposal-contract',headers={'Authorization':'Bearer '+agent})
        assert response.status_code==(403 if late=='revocation' else 503),response.text
        assert 'registry_bindings' not in response.text
