"""Content-pinned, protected-startup catalogs; never execution authority.

Construct Registry only from trusted control configuration, never request JSON.
Matching registration is NOT a filesystem/data integrity check or a resource
enforcement probe. Approval and execution must independently perform those gates.
No paths are opened, commands run, or Store facts written by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from jsonschema import Draft202012Validator, SchemaError

from .hybrid_goals import bounded_copy, digest, validate_request
from .hybrid_protocol import HASH, ID, TEXT, ProtocolError, array, enum, obj, validate_schema
from .store import canonical

JSON_OBJECT = {'type': 'object'}
STRINGS = {**array(TEXT, 128), 'uniqueItems': True}
TOOL = obj({'adapter': ID, 'definition': JSON_OBJECT})
COMMAND = obj({'tool_id': ID, 'argv': {**array(TEXT, 128), 'minItems': 1},
               'parameter_schema': JSON_OBJECT, 'network': enum('none', 'allowlist'),
               'allowed_hosts': STRINGS})
DATASET = obj({'version_hash': HASH,
               'purposes': {**array(enum('training', 'validation', 'evaluation', 'reference'), 4),
                            'uniqueItems': True, 'minItems': 1},
               'access': enum('READ_ONLY', 'PROTECTED_EVALUATOR_ONLY'),
               'source': obj({'adapter': ID, 'reference': ID})})
RULE = obj({'definition': JSON_OBJECT, 'requires_datasets': {'type': 'boolean'}})


def catalog_map(item):
    return {'type': 'object', 'maxProperties': 128, 'propertyNames': ID,
            'additionalProperties': item}


CATALOG = obj({'schema_version': {'const': '1.0'}, 'project_id': ID,
               'data_mode': enum('live', 'fixture'),
               'tools': catalog_map(TOOL), 'commands': catalog_map(COMMAND),
               'runtime_profile': JSON_OBJECT, 'resource_profile': JSON_OBJECT,
               'datasets': catalog_map(DATASET), 'evaluation_rules': catalog_map(RULE),
               'project_policy': obj({'network_access': enum('none', 'allowlist'),
                                      'allowed_hosts': STRINGS, 'configuration': JSON_OBJECT})})


def _bindings(config):
    # Domain-separated hashes include fixed project/mode, even for empty catalogs.
    context = [config['project_id'], config['data_mode']]
    return {name: digest([name, context, value]) for name, value in (
        ('tool_registry_hash', config['tools']),
        ('command_registry_hash', config['commands']),
        ('runtime_profile_hash', config['runtime_profile']),
        ('resource_profile_hash', config['resource_profile']),
        ('dataset_registry_hash', {'datasets': config['datasets'], 'rules': config['evaluation_rules']}))}


@dataclass(frozen=True, init=False)
class Registry:
    """Detached immutable JSON bytes, installed by protected control startup.

    A caller able to replace this service/configuration is in the trusted control
    boundary. The class is not a sandbox against arbitrary in-process Python.
    Opaque profile JSON is deliberately not interpreted as enforceability proof.
    """
    _raw: bytes

    def __init__(self, trusted_config):
        config = bounded_copy(trusted_config)
        try:
            validate_schema(CATALOG, config)
        except ProtocolError as exc:
            raise ProtocolError('invalid trusted registry configuration') from exc
        policy = config['project_policy']
        if policy['network_access'] == 'none' and policy['allowed_hosts']:
            raise ProtocolError('network-disabled project policy names hosts')
        for section in ('tools', 'commands', 'datasets', 'evaluation_rules'):
            if any(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', key) is None for key in config[section]):
                raise ProtocolError('invalid registered identifier')
        for command in config['commands'].values():
            if command['tool_id'] not in config['tools']:
                raise ProtocolError('registered command references unknown tool')
            if command['network'] == 'none' and command['allowed_hosts']:
                raise ProtocolError('network-disabled registered command names hosts')
            if not command['argv'][0] or any('\x00' in arg for arg in command['argv']):
                raise ProtocolError('invalid registered argv')
            try:
                Draft202012Validator.check_schema(command['parameter_schema'])
            except (SchemaError, RecursionError) as exc:
                raise ProtocolError('invalid registered parameter schema') from exc
        for dataset in config['datasets'].values():
            if dataset['access'] == 'PROTECTED_EVALUATOR_ONLY' and 'training' in dataset['purposes']:
                raise ProtocolError('protected evaluation registration cannot grant training')
        object.__setattr__(self, '_raw', canonical(config))

    @property
    def bindings(self):
        return _bindings(json.loads(self._raw))

    @property
    def config_hash(self):
        return digest(json.loads(self._raw))

    def resolve(self, proposal):
        """Private confirmation binding, NOT approval, lease, or executable scope.

        Whole proposal and whole trusted config are bound, including project
        policy and unrelated catalog entries. Any config change requires a new
        confirmation; exact candidate/resource/OS gates still belong downstream.
        """
        proposal = bounded_copy(proposal)
        if not isinstance(proposal, dict) or proposal.get('schema_version') != '1.1':
            raise ProtocolError('explicit schema1.1 boundaries required')
        # Reuse draft semantic bounds without accepting caller identity/authority.
        validate_request({'action': 'propose_goal_draft', 'project_id': proposal.get('project_id'),
                          'data_mode': proposal.get('data_mode'), 'actor': {'id': 'registry_validator', 'kind': 'agent'},
                          'idempotency_key': 'registry_validation',
                          'expected_revision': proposal.get('contract_version', 0) - 1
                          if type(proposal.get('contract_version')) is int else -1,
                          'proposal': proposal})
        config = json.loads(self._raw)
        if (proposal['project_id'], proposal['data_mode']) != (config['project_id'], config['data_mode']):
            raise ProtocolError('registry project or mode mismatch', 'PERMISSION_DENIED')
        if proposal['registry_bindings'] != _bindings(config):
            raise ProtocolError('registry or profile content changed', 'VERSION_CONFLICT')
        tools = proposal['allowed_tools']
        if any(tool not in config['tools'] for tool in tools):
            raise ProtocolError('unregistered allowed tool')
        scope = proposal['scope']
        policy = config['project_policy']
        if scope['network_access'] == 'allowlist' and (
                policy['network_access'] != 'allowlist' or
                not set(scope['allowed_hosts']) <= set(policy['allowed_hosts'])):
            raise ProtocolError('declared network exceeds registered project policy', 'PERMISSION_DENIED')
        for name in scope['allowed_command_templates']:
            command = config['commands'].get(name)
            if command is None or command['tool_id'] not in tools:
                raise ProtocolError('unregistered command or tool outside declared scope')
            if command['network'] == 'allowlist' and (
                    scope['network_access'] != 'allowlist' or
                    not set(command['allowed_hosts']) <= set(scope['allowed_hosts'])):
                raise ProtocolError('registered command network exceeds declared scope')
        data = proposal['evaluation_data']
        rule_id = data['evaluation_rule']['id']
        rule = config['evaluation_rules'].get(rule_id)
        if rule is None or data['evaluation_rule']['version_hash'] != digest(rule):
            raise ProtocolError('unregistered or changed evaluation rule')
        if rule['requires_datasets'] and not data['datasets']:
            raise ProtocolError('registered evaluation rule requires data')
        for declaration in data['datasets']:
            dataset = config['datasets'].get(declaration['dataset_id'])
            if dataset is None or dataset['version_hash'] != declaration['version_hash']:
                raise ProtocolError('unregistered or changed dataset version')
            if declaration['purpose'] not in dataset['purposes'] or declaration['access'] != dataset['access']:
                raise ProtocolError('dataset declaration exceeds registered boundary', 'PERMISSION_DENIED')
        if any(tool['adapter']=='original_a_workflow_v2' for tool in config['tools'].values()):
            from .hybrid_a_workflow_profile import validate_approval
            validate_approval(proposal,config)
        proposal_hash, config_hash = digest(proposal), digest(config)
        return {'state': 'NOT_EXECUTABLE', 'project_id': config['project_id'],
                'data_mode': config['data_mode'], 'proposal_hash': proposal_hash,
                'config_hash': config_hash,
                'scope_hash': digest(['hybrid.confirmation.scope.v1', proposal_hash, config_hash]),
                'registry_bindings': _bindings(config)}
