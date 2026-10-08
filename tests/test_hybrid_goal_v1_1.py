from copy import deepcopy
import json
from pathlib import Path

import pytest

from rlflow.hybrid_protocol import validate, schemas, ProtocolError
from rlflow.hybrid_goals import propose, digest, SECTIONS, revision_key
from rlflow.observation import enable
from rlflow.store import Store
from rlflow.web_auth import Principal


def legacy():
    return json.loads(Path('docs/rlflow_hybrid_spec_v1/examples/goal.fixture.json').read_text())


def explicit():
    p=legacy();p['schema_version']='1.1'
    p['allowed_tools']=[]
    p['registry_bindings']={name:digest({'fixture_declaration':name}) for name in (
        'tool_registry_hash','command_registry_hash','runtime_profile_hash','resource_profile_hash','dataset_registry_hash')}
    p['evaluation_data']={'mode':'EXPLICIT_NONE','datasets':[],
        'evaluation_rule':{'id':'fixture_rule','version_hash':digest({'fixture_rule':'fixed tests and independent review'})}}
    return p


def test_legacy_schema_and_proposal_remain_valid_and_distinct():
    validate('goal',legacy());validate('goal_v1_1',explicit())
    assert schemas()['goal']['$id']=='urn:rlflow:spec:goal-proposal:1.0'
    assert schemas()['goal_v1_1']['$id']=='urn:rlflow:spec:goal-proposal:1.1'
    with pytest.raises(ProtocolError):validate('goal',explicit())
    with pytest.raises(ProtocolError):validate('goal_v1_1',legacy())


@pytest.mark.parametrize('field',['allowed_tools','registry_bindings','evaluation_data'])
def test_no_implicit_tools_profiles_or_data_defaults(field):
    p=explicit();del p[field]
    with pytest.raises(ProtocolError):validate('goal_v1_1',p)


@pytest.mark.parametrize('bad',['duplicate_tool','missing_binding','bad_hash','none_with_data','path_dataset','extra_field'])
def test_closed_explicit_boundaries_reject_malformed_declarations(bad):
    p=explicit()
    if bad=='duplicate_tool':p['allowed_tools']=['cpu_exec','cpu_exec']
    elif bad=='missing_binding':del p['registry_bindings']['command_registry_hash']
    elif bad=='bad_hash':p['registry_bindings']['runtime_profile_hash']='unversioned-name'
    elif bad=='extra_field':p['evaluation_data']['approved_by']='human'
    else:
        p['evaluation_data']['datasets']=[{'dataset_id':'../host/path' if bad=='path_dataset' else 'fixture_dataset',
            'version_hash':digest({}), 'purpose':'evaluation','access':'PROTECTED_EVALUATOR_ONLY'}]
        if bad=='path_dataset':p['evaluation_data']['mode']='REGISTERED_DATASETS'
    with pytest.raises(ProtocolError):validate('goal_v1_1',p)


def test_theoretical_research_can_explicitly_declare_no_dataset_without_faking_one(tmp_path):
    p=explicit();p['goal_kind']='research'
    validate('goal_v1_1',p)
    assert p['evaluation_data']['mode']=='EXPLICIT_NONE' and p['evaluation_data']['datasets']==[]
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    actor=Principal('fixture_operator','agent',{'operator'},{'project_fixture'})
    result=propose(store,p,principal=actor,project_id='project_fixture',data_mode='fixture',idempotency_key='theory',expected_revision=0)
    assert result['contract']['state']=='DRAFT' and result['contract']['approval_id'] is None
    assert not store.objects('sessions') and not store.objects('approvals')
    assert store.recover()==store.audit()==store.replay()


@pytest.mark.parametrize('field',['tool_registry_hash','command_registry_hash','runtime_profile_hash','resource_profile_hash','dataset_registry_hash'])
def test_every_registry_binding_must_be_explicit(field):
    p=explicit();del p['registry_bindings'][field]
    with pytest.raises(ProtocolError):validate('goal_v1_1',p)


@pytest.mark.parametrize('target,field', [('rule','id'),('rule','version_hash'),('dataset','dataset_id'),('dataset','version_hash'),('dataset','purpose'),('dataset','access')])
def test_every_dataset_and_rule_binding_must_be_explicit(target,field):
    p=explicit();data=p['evaluation_data'];data['mode']='REGISTERED_DATASETS'
    data['datasets']=[{'dataset_id':'fixture_dataset','version_hash':digest({}), 'purpose':'evaluation','access':'PROTECTED_EVALUATOR_ONLY'}]
    del (data['evaluation_rule'] if target=='rule' else data['datasets'][0])[field]
    with pytest.raises(ProtocolError):validate('goal_v1_1',p)


def test_registered_mode_cannot_have_empty_datasets():
    p=explicit();p['evaluation_data']['mode']='REGISTERED_DATASETS'
    with pytest.raises(ProtocolError):validate('goal_v1_1',p)


def test_same_dataset_id_cannot_bind_two_versions_or_access_policies(tmp_path):
    p=explicit();data=p['evaluation_data'];data['mode']='REGISTERED_DATASETS'
    data['datasets']=[{'dataset_id':'fixture_dataset','version_hash':digest({'v':version}), 'purpose':'evaluation',
        'access':access} for version,access in [(1,'PROTECTED_EVALUATOR_ONLY'),(2,'READ_ONLY')]]
    # Different objects pass JSON uniqueItems; core enforces reference identity.
    validate('goal_v1_1',p)
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture');before=store.replay()
    actor=Principal('fixture_operator','agent',{'operator'},{'project_fixture'})
    with pytest.raises(ProtocolError,match='dataset IDs'):
        propose(store,p,principal=actor,project_id='project_fixture',data_mode='fixture',idempotency_key='ambiguous',expected_revision=0)
    assert store.replay()==before and all(not store.objects(s) for s in SECTIONS)


def test_research_registered_data_is_only_an_unapproved_declaration(tmp_path):
    p=explicit();p['goal_kind']='research';p['evaluation_data']['mode']='REGISTERED_DATASETS'
    p['evaluation_data']['datasets']=[{'dataset_id':'fixture_dataset','version_hash':digest({'version':1}),
        'purpose':'evaluation','access':'PROTECTED_EVALUATOR_ONLY'}]
    validate('goal_v1_1',p)
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    actor=Principal('fixture_operator','agent',{'operator'},{'project_fixture'})
    result=propose(store,p,principal=actor,project_id='project_fixture',data_mode='fixture',idempotency_key='research',expected_revision=0)
    assert result['contract']['state']=='DRAFT' and result['contract']['approval_id'] is None
    assert not store.objects('sessions') and not store.objects('approvals') and not store.objects('jobs')
    assert store.recover()==store.audit()==store.replay()


def test_upgrade_requires_new_immutable_revision_not_default_backfill(tmp_path):
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    actor=Principal('fixture_operator','agent',{'operator'},{'project_fixture'});old=legacy()
    args={'principal':actor,'project_id':'project_fixture','data_mode':'fixture'}
    original=propose(store,old,**args,idempotency_key='legacy',expected_revision=0)
    upgraded=explicit();upgraded['contract_version']=2
    result=propose(store,upgraded,**args,idempotency_key='explicit',expected_revision=1)
    assert original['contract']['hash']==digest(old) and result['contract']['hash']!=original['contract']['hash']
    assert store.get(SECTIONS[0],revision_key(old))['contract']==original['contract']
    new=store.get(SECTIONS[0],revision_key(upgraded))
    assert new['previous_hash']==original['contract']['hash']
    assert {r['path'] for r in new['changes']}=={'/schema_version','/contract_version','/allowed_tools','/registry_bindings','/evaluation_data'}
    assert result['contract']['state']=='DRAFT' and result['contract']['approval_id'] is None
    assert store.recover()==store.audit()==store.replay()
