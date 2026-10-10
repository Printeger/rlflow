"""Pure two-phase fixture installation facts; no runtime or disk adoption.

Under construction: not wired into Store until an actual protected installation
owner/guard exists. Catalog references a preallocated indexed INTENT key/version
instead of its digest, avoiding catalog/intent/release-seal circular hashing.
"""
import hashlib

from .files import relative_name
from .hybrid_goals import check_bytes, digest
from .hybrid_protocol import ID, HASH, obj, array, validate_schema
from .hybrid_runtime_boundary import _path, _chain_value, BoundaryDenied, policy_source
from .store import Conflict, sha

SECTIONS = ('hybrid_runtime_installation_intents', 'hybrid_runtime_installation_publications')
EVENTS = ('HYBRID_RUNTIME_INSTALLATION_INTENT', 'HYBRID_RUNTIME_INSTALLATION_READY')
COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 2**63 - 1}
POSITIVE = {**COUNT, 'minimum': 1}
NUMBER = {'type': 'integer', 'minimum': 0, 'maximum': 2**64 - 1}
RAW_HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
PAIR = {**array(NUMBER, 2), 'minItems': 2}
TRIPLE = {**array(NUMBER, 3), 'minItems': 3}
CHAIN = {**array(TRIPLE, 64), 'minItems': 1}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
SCOPE = obj({'reserved_path': PATH, 'directory_chain': CHAIN})
REF = obj({'intent_key': ID, 'accepted_state_version': POSITIVE})
CATALOG = obj({'version': {'const': 1}, 'mode': {'const': 'HYBRID_LEGACY_DENIED'},
    'scopes': {**array(SCOPE, 16), 'minItems': 1}, 'installation_ref': REF,
    'execution_enabled': {'const': False}, 'release_enabled': {'const': False}})
DESCRIPTOR = obj({'version': {'const': 1}, 'mode': {'const': 'BOUND_HYBRID_NONEXECUTING'},
    'catalog_path': PATH, 'catalog_sha256': RAW_HASH, 'catalog_parent_chain': CHAIN,
    'catalog_identity': PAIR})
SEAL = obj({'descriptor': DESCRIPTOR, 'catalog': CATALOG, 'release_id': RAW_HASH,
    'release_manifest': {'type': 'object', 'minProperties': 1, 'maxProperties': 1024,
                         'additionalProperties': RAW_HASH}})
BINDING = obj({'store_root': PATH, 'store_root_chain': CHAIN, 'database_identity': PAIR,
    'working_namespace': PATH, 'working_namespace_chain': CHAIN,
    'release_path': PATH, 'release_parent_chain': CHAIN, 'bootstrap_template_hash': RAW_HASH})
COMMON = {'project_id': ID, 'data_mode': {'const': 'fixture'}, 'store_epoch': ID,
    'installation_id': ID, 'idempotency_key': ID, 'expected_state_version': COUNT}
INTENT_REQUEST = obj({**COMMON, 'action': {'const': 'prepare_fixture_runtime_installation'}})
READY_REQUEST = obj({**COMMON, 'action': {'const': 'publish_fixture_runtime_installation'},
    'intent_key': ID, 'intent_hash': HASH})
from .hybrid_live_domain import PROFILE as LIVE_PROFILE,PREPARE as LIVE_PREPARE,PUBLISH as LIVE_PUBLISH
LIVE_COMMON={**COMMON,'data_mode':{'const':'live'},'domain_profile':{'const':LIVE_PROFILE}}
INTENT_REQUEST={'oneOf':[INTENT_REQUEST,obj({**LIVE_COMMON,'action':{'const':LIVE_PREPARE}})]}
READY_REQUEST={'oneOf':[READY_REQUEST,obj({**LIVE_COMMON,'action':{'const':LIVE_PUBLISH},
    'intent_key':ID,'intent_hash':HASH})]}
INTENT = obj({'request': INTENT_REQUEST, 'request_hash': HASH, 'binding': BINDING,
    'expected_seal': SEAL, 'accepted_state_version': POSITIVE,
    'state': {'const': 'LEGACY_DENIED_UNPUBLISHED'}, 'execution_enabled': {'const': False},
    'release_enabled': {'const': False}})
READY = obj({'request': READY_REQUEST, 'request_hash': HASH, 'accepted_state_version': POSITIVE,
    'catalog_sha256': RAW_HASH, 'release_id': RAW_HASH,
    'state': {'const': 'LEGACY_DENIED_READY_NONEXECUTING'},
    'execution_enabled': {'const': False}, 'release_enabled': {'const': False}})


def _concrete_path(value):
    try:
        path = _path(value)
    except BoundaryDenied as error:
        raise Conflict('concrete historical installation path required') from error
    if type(value) is not str or str(path) != value:
        raise Conflict('canonical historical installation path required')
    return path


def _chain(value, path):
    try:
        _chain_value(value, path)
    except BoundaryDenied as error:
        raise Conflict('actual historical installation chain required') from error


def intent_key(request):
    return 'runtime_install_intent_' + sha([request['project_id'], request['data_mode'],
                                          request['installation_id'], request['idempotency_key']])


def publication_key(request):
    return 'runtime_install_ready_' + sha([request['project_id'], request['data_mode'], request['installation_id']])


def event_inputs(value):
    request = value['request']
    return {} if request['action'] in ('prepare_fixture_runtime_installation',LIVE_PREPARE) else {
        'runtime_installation_intent': [request['intent_key'], request['intent_hash']]}


def expected_objects(section, key, value):
    return [(section, key, digest(value))]


def validate_record(section, key, value):
    if section not in SECTIONS:
        raise Conflict('unknown runtime installation section')
    check_bytes(value, 1024**2)
    validate_schema(INTENT if section == SECTIONS[0] else READY, value)
    request = value['request']
    expected_key = intent_key(request) if section == SECTIONS[0] else publication_key(request)
    if (key != expected_key or value['request_hash'] != digest(request) or
            type(request['expected_state_version']) is not int or
            type(value['accepted_state_version']) is not int or
            value['accepted_state_version'] != request['expected_state_version'] + 1):
        raise Conflict('runtime installation identity or version differs')
    if section == SECTIONS[1]:
        return
    # This first slice ONLY installs a newly created isolated store. A production
    # migration/upgrade cannot silently reuse this fresh-install contract.
    if request['expected_state_version'] != 0:
        raise Conflict('fresh isolated installation requires an empty core')
    binding = value['binding']; seal = value['expected_seal']; descriptor = seal['descriptor']
    catalog = seal['catalog']
    if (type(catalog['version']) is not int or type(descriptor['version']) is not int or
            catalog['installation_ref'] != {'intent_key': key, 'accepted_state_version': value['accepted_state_version']} or
            descriptor['catalog_sha256'] != sha(catalog) or seal['release_id'] != sha(seal['release_manifest'])):
        raise Conflict('original catalog reference or expected release seal differs')
    roots = []
    for path_name, chain_name in [('store_root', 'store_root_chain'), ('working_namespace', 'working_namespace_chain')]:
        path = _concrete_path(binding[path_name]); _chain(binding[chain_name], path)
        if len(path.parts) < 3:
            raise Conflict('concrete isolated installation scope required')
        roots.append(path)
    for path, chain in [(descriptor['catalog_path'], descriptor['catalog_parent_chain']),
                        (binding['release_path'], binding['release_parent_chain'])]:
        _chain(chain, _concrete_path(path).parent)
    if any(type(number) is not int for number in descriptor['catalog_identity'] + binding['database_identity']):
        raise Conflict('actual integer installation inode identities required')
    actual_scopes = set()
    for scope in catalog['scopes']:
        path = _concrete_path(scope['reserved_path']); _chain(scope['directory_chain'], path)
        if len(path.parts) < 3 or str(path) in actual_scopes:
            raise Conflict('unique bounded installation tombstone required')
        actual_scopes.add(str(path))
    if any(str(root) not in actual_scopes for root in roots):
        raise Conflict('installation catalog omits actual store or working namespace')
    scoped = {row['reserved_path']: row['directory_chain'] for row in catalog['scopes']}
    if (scoped[binding['store_root']] != binding['store_root_chain'] or
            scoped[binding['working_namespace']] != binding['working_namespace_chain'] or
            roots[0] == roots[1] or roots[0] in roots[1].parents or roots[1] in roots[0].parents or
            binding['store_root_chain'][-1][:2] in [row[:2] for row in binding['working_namespace_chain']] or
            binding['working_namespace_chain'][-1][:2] in [row[:2] for row in binding['store_root_chain']]):
        raise Conflict('actual store/working roots or original catalog physical scopes differ')
    for name in seal['release_manifest']:
        relative_name(name)
    if not {'rlflow/hybrid_runtime_boundary.py', 'rlflow/runtime_boundary_policy.py'} <= set(seal['release_manifest']):
        raise Conflict('guarded release omits mandatory boundary code or policy')
    manifest = seal['release_manifest']; policy_name = 'rlflow/runtime_boundary_policy.py'
    if (manifest[policy_name] != hashlib.sha256(policy_source(descriptor)).hexdigest() or
            binding['bootstrap_template_hash'] != sha({name: value for name, value in manifest.items() if name != policy_name})):
        raise Conflict('generated fixed policy or original bootstrap template differs from release seal')


def validate_links(value, lookup):
    request = value['request']
    if request['action'] in ('prepare_fixture_runtime_installation',LIVE_PREPARE):
        return
    original = lookup(SECTIONS[0], request['intent_key'])
    if original is None:
        raise Conflict('runtime publication requires original installation intent')
    validate_record(SECTIONS[0], request['intent_key'], original)
    if (digest(original) != request['intent_hash'] or
            any(request[name] != original['request'][name] for name in
                ('project_id', 'data_mode', 'store_epoch', 'installation_id')) or
            request['expected_state_version'] != original['accepted_state_version'] or
            value['catalog_sha256'] != original['expected_seal']['descriptor']['catalog_sha256'] or
            value['release_id'] != original['expected_seal']['release_id']):
        raise Conflict('publication differs from original source/seal or fresh CAS')


def validate_transition(payload, lookup, *, event_type, key, object_id, producer, version, registration):
    if (type(payload) is not dict or set(payload) != {'format', 'put', 'delete', 'details'} or
            type(payload['format']) is not int or payload['format'] != 2 or
            type(payload['put']) is not list or payload['delete'] != [] or payload['details'] is not None or
            event_type not in EVENTS):
        raise Conflict('closed runtime installation append required')
    section = SECTIONS[EVENTS.index(event_type)]
    rows = {}; markers = {}
    for row in payload['put']:
        if type(row) is not list or len(row) != 3 or row[0] != section or type(row[1]) is not str:
            raise Conflict('runtime installation extra object descriptor')
        if row[1]:
            if row[1] in rows:
                raise Conflict('runtime installation duplicate object')
            rows[row[1]] = row[2]
        else:
            if section in markers:
                raise Conflict('runtime installation duplicate section marker')
            markers[section] = row[2]
    if len(rows) != 1 or key not in rows:
        raise Conflict('one original immutable installation fact required')
    value = rows[key]; validate_record(section, key, value); request = value['request']
    if (lookup(section, '') is not None or markers != {section: {}} or
            lookup(section, key) is not None or object_id != request['installation_id'] or
            producer != 'hybrid-installer' or version != value['accepted_state_version'] or
            registration != (request['project_id'], request['data_mode'])):
        raise Conflict('runtime installation original event differs')
    validate_links(value, lookup)


def validate_persisted(state):
    for section in SECTIONS:
        records = state.get(section, {})
        if not isinstance(records, dict) or len(records) > 1:
            raise Conflict('fresh fixture has at most one immutable installation per phase')
        for key, value in records.items():
            validate_record(section, key, value)


def validate_complete(state, registration=None, event_lookup=None, *, event_summary):
    validate_persisted(state)
    lookup = lambda section, key: state.get(section, {}).get(key)
    ordered = sorted([(section, key, value) for section in SECTIONS for key, value in state.get(section, {}).items()],
                     key=lambda row: row[2]['accepted_state_version'])
    for section, key, value in ordered:
        request = value['request']; validate_links(value, lookup)
        expected = ((EVENTS[SECTIONS.index(section)], 'hybrid-installer', request['installation_id'],
                     value['accepted_state_version']), expected_objects(section, key, value), event_inputs(value))
        if (registration != (request['project_id'], request['data_mode']) or
                value['accepted_state_version'] > state['version'] or event_lookup is None or event_lookup(key) != expected):
            raise Conflict('runtime installation original source/history differs')
    tip = None if not ordered else (ordered[-1][1], ordered[-1][2]['accepted_state_version'])
    if event_summary != (tip, len(ordered)):
        raise Conflict('runtime installation historical tip/count differs')
