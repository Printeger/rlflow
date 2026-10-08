from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from rlflow.hybrid_goals import digest
from rlflow.hybrid_protocol import ProtocolError
from rlflow.hybrid_registry import Registry
from rlflow.observation import enable
from rlflow.store import Store
from tests.test_hybrid_goal_v1_1 import explicit, legacy


def catalog():
    return {'schema_version': '1.0', 'project_id': 'project_fixture', 'data_mode': 'fixture',
            'tools': {'cpu_exec': {'adapter': 'controlled_cpu', 'definition': {'version': 'fixture_v1'}}},
            'commands': {'fixture_test': {'tool_id': 'cpu_exec', 'argv': ['fixture-python', '-m', 'pytest'],
                                         'parameter_schema': {'type': 'object', 'additionalProperties': False},
                                         'network': 'none', 'allowed_hosts': []}},
            'runtime_profile': {'adapter': 'fixture', 'capabilities': []},
            'resource_profile': {'enforcement': 'UNKNOWN'},
            'datasets': {'fixture_data': {'version_hash': digest({'data': 'registered fixture version'}),
                                        'purposes': ['evaluation', 'reference'], 'access': 'PROTECTED_EVALUATOR_ONLY',
                                        'source': {'adapter': 'registered_fixture', 'reference': 'fixture_data_v1'}}},
            'evaluation_rules': {'fixture_rule': {'definition': {'method': 'fixed_fixture_tests'},
                                                 'requires_datasets': False}},
            'project_policy': {'network_access': 'none', 'allowed_hosts': [],
                               'configuration': {'protected_control': 'external', 'execution_enabled': False}}}


def bound(config=None):
    config = catalog() if config is None else config
    registry = Registry(config)
    p = explicit()
    p['allowed_tools'] = ['cpu_exec']
    p['registry_bindings'] = registry.bindings
    p['evaluation_data']['evaluation_rule']['version_hash'] = digest(config['evaluation_rules']['fixture_rule'])
    return registry, p


def with_data(p, config):
    dataset = config['datasets']['fixture_data']
    p['evaluation_data'].update(mode='REGISTERED_DATASETS', datasets=[{
        'dataset_id': 'fixture_data', 'version_hash': dataset['version_hash'],
        'purpose': 'evaluation', 'access': dataset['access']}])


def test_resolve_only_binds_no_authority_or_store_effect(tmp_path):
    registry, p = bound()
    store = Store(tmp_path/'state'); enable(store, 'project_fixture', data_mode='fixture')
    before = store.audit()
    result = registry.resolve(p)
    assert result['state'] == 'NOT_EXECUTABLE'
    assert result['proposal_hash'] == digest(p) and result['config_hash'] == registry.config_hash
    assert result['scope_hash'] == digest(['hybrid.confirmation.scope.v1', digest(p), registry.config_hash])
    assert store.audit() == before and not store.objects('sessions') and not store.objects('approvals')
    assert not any(key in result for key in ('argv', 'source', 'runtime_profile', 'resource_profile'))


def test_catalog_inputs_and_results_are_detached_and_immutable():
    config = catalog(); registry, p = bound(config)
    original = registry.resolve(p)
    config['commands']['fixture_test']['argv'].append('changed')
    config['project_policy']['configuration']['execution_enabled'] = True
    registry.bindings['tool_registry_hash'] = digest('forged')
    result = registry.resolve(p); result['registry_bindings']['dataset_registry_hash'] = digest('forged')
    assert registry.resolve(p) == original
    with pytest.raises(FrozenInstanceError):registry._raw = b'{}'


@pytest.mark.parametrize('section', ['tools', 'commands', 'runtime_profile', 'resource_profile', 'datasets', 'evaluation_rules'])
def test_registered_content_drift_rejects_old_proposal(section):
    config = catalog(); _, p = bound(config)
    if section == 'tools':config[section]['cpu_exec']['definition']['version'] = 'v2'
    elif section == 'commands':config[section]['fixture_test']['argv'].append('--different')
    elif section in ('runtime_profile', 'resource_profile'):config[section]['changed'] = True
    elif section == 'datasets':config[section]['fixture_data']['version_hash'] = digest('changed')
    else:config[section]['fixture_rule']['requires_datasets'] = True
    with pytest.raises(ProtocolError) as error:Registry(config).resolve(p)
    assert error.value.code == 'VERSION_CONFLICT'


def test_policy_drift_changes_confirmation_scope_even_if_five_bindings_same():
    config = catalog(); registry, p = bound(config)
    result = registry.resolve(p)
    config['project_policy']['configuration']['protected_control'] = 'another_registered_policy'
    changed = Registry(config)
    assert changed.bindings == registry.bindings
    assert changed.resolve(p)['scope_hash'] != result['scope_hash']
    assert changed.resolve(p)['config_hash'] != result['config_hash']


@pytest.mark.parametrize('field', ['objective', 'scope', 'budget', 'stop_rules', 'risk', 'global_conditions', 'goal_kind'])
def test_complete_proposal_is_bound_not_just_writable_paths(field):
    registry, p = bound(); original = registry.resolve(p)
    if field == 'objective':p[field] += ' clarified'
    elif field == 'scope':p[field]['protected_paths'].append('more_protected/')
    elif field == 'budget':p[field]['wall_seconds'] += 1
    elif field == 'stop_rules':p[field].append('additional stop')
    elif field == 'risk':p[field] = 'high'
    elif field == 'global_conditions':p[field][0]['description'] += ' clarified'
    else:p[field] = 'research'
    assert registry.resolve(p)['scope_hash'] != original['scope_hash']


@pytest.mark.parametrize('bad', ['legacy', 'project', 'mode', 'unknown_tool', 'unknown_command', 'command_tool',
                                'unknown_rule', 'changed_rule', 'rule_needs_data', 'dataset_version',
                                'unknown_dataset', 'dataset_access', 'dataset_purpose'])
def test_invalid_registered_boundaries_reject(bad):
    config = catalog()
    if bad == 'rule_needs_data':config['evaluation_rules']['fixture_rule']['requires_datasets'] = True
    registry, p = bound(config)
    if bad == 'legacy':p = legacy()
    elif bad in ('project', 'mode'):p['project_id' if bad == 'project' else 'data_mode'] = 'other_project' if bad == 'project' else 'live'
    elif bad == 'unknown_tool':p['allowed_tools'].append('unknown_tool')
    elif bad == 'unknown_command':p['scope']['allowed_command_templates'].append('unknown_command')
    elif bad == 'command_tool':p['allowed_tools'] = []
    elif bad == 'unknown_rule':p['evaluation_data']['evaluation_rule']['id'] = 'unknown_rule'
    elif bad == 'changed_rule':p['evaluation_data']['evaluation_rule']['version_hash'] = digest('changed')
    elif bad != 'rule_needs_data':
        with_data(p, config)
        d = p['evaluation_data']['datasets'][0]
        if bad == 'dataset_version':d['version_hash'] = digest('changed')
        elif bad == 'unknown_dataset':d['dataset_id'] = 'unknown_dataset'
        elif bad == 'dataset_access':d['access'] = 'READ_ONLY'
        else:d['purpose'] = 'training'
    with pytest.raises(ProtocolError):registry.resolve(p)


def test_registered_protected_dataset_and_requires_data_rule_match():
    config = catalog(); config['evaluation_rules']['fixture_rule']['requires_datasets'] = True
    registry, p = bound(config); with_data(p, config)
    assert registry.resolve(p)['state'] == 'NOT_EXECUTABLE'


def network_catalog():
    config = catalog()
    config['project_policy'].update(network_access='allowlist', allowed_hosts=['fixture.example', 'other.example'])
    config['commands']['fixture_test'].update(network='allowlist', allowed_hosts=['fixture.example'])
    return config


@pytest.mark.parametrize('bad', ['proposal_none', 'command_host', 'policy_host', 'policy_none'])
def test_network_three_level_subset(bad):
    config = network_catalog()
    if bad == 'policy_none':config['project_policy'].update(network_access='none', allowed_hosts=[])
    registry, p = bound(config)
    p['scope'].update(network_access='allowlist', allowed_hosts=['fixture.example'])
    if bad == 'proposal_none':p['scope'].update(network_access='none', allowed_hosts=[])
    elif bad == 'command_host':p['scope']['allowed_hosts'] = ['other.example']
    elif bad == 'policy_host':p['scope']['allowed_hosts'].append('outside.example')
    with pytest.raises(ProtocolError):registry.resolve(p)


def test_network_registered_subset_positive():
    registry, p = bound(network_catalog())
    p['scope'].update(network_access='allowlist', allowed_hosts=['fixture.example', 'other.example'])
    assert registry.resolve(p)['state'] == 'NOT_EXECUTABLE'


@pytest.mark.parametrize('bad', ['oversize', 'nan', 'unknown_field', 'missing_profile', 'invalid_id', 'too_many',
                                'unknown_dependency', 'empty_argv', 'nul_argv', 'invalid_schema',
                                'protected_training', 'none_policy_hosts', 'none_command_hosts'])
def test_invalid_catalog_rejects_without_secret_echo(bad):
    config = catalog(); secret = 'FIXTURE_SECRET_NOT_FOR_ERRORS'
    if bad == 'oversize':config['runtime_profile']['large'] = secret * 20000
    elif bad == 'nan':config['runtime_profile']['bad'] = float('nan')
    elif bad == 'unknown_field':config[secret] = True
    elif bad == 'missing_profile':del config['resource_profile']
    elif bad == 'invalid_id':config['tools'][secret+'/path'] = config['tools']['cpu_exec']
    elif bad == 'too_many':config['tools'] = {f'tool_{i}':config['tools']['cpu_exec'] for i in range(129)}
    elif bad == 'unknown_dependency':config['commands']['fixture_test']['tool_id'] = secret
    elif bad in ('empty_argv', 'nul_argv'):config['commands']['fixture_test']['argv'] = ['' if bad == 'empty_argv' else secret+'\x00']
    elif bad == 'invalid_schema':config['commands']['fixture_test']['parameter_schema'] = {'type': secret}
    elif bad == 'protected_training':config['datasets']['fixture_data']['purposes'].append('training')
    elif bad == 'none_policy_hosts':config['project_policy']['allowed_hosts'] = [secret]
    else:config['commands']['fixture_test']['allowed_hosts'] = [secret]
    with pytest.raises(ProtocolError) as error:Registry(config)
    assert secret not in str(error.value)


def test_parameter_schema_is_metadata_and_no_remote_reference_is_loaded(monkeypatch):
    import socket
    import subprocess
    def forbidden(*args, **kwargs):raise AssertionError('registry performed external action')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    config = catalog()
    config['commands']['fixture_test']['parameter_schema'] = {'$ref': 'https://fixture.invalid/never-fetched'}
    config['commands']['fixture_test']['argv'].append('')  # Empty argument is a valid argv value.
    registry, p = bound(config)
    assert registry.resolve(p)['state'] == 'NOT_EXECUTABLE'


def test_bindings_domain_separate_empty_catalog_project_and_mode():
    config = catalog(); config['commands'] = {}; config['tools'] = {}
    a = Registry(config).bindings
    config['data_mode'] = 'live'; b = Registry(config).bindings
    config['project_id'] = 'other'; c = Registry(config).bindings
    assert set(a) == set(b) == set(c) and all(a[key] != b[key] != c[key] for key in a)
    assert a['tool_registry_hash'] != a['command_registry_hash']
