"""Immutable non-executing preparation facts (private core domain).

Pure validation performs no file IO or runtime actions. Live owner/service
integration is required separately; JSON records are never execution authority.
"""
from .execution_adapter import PROFILE, PACKET, FILES
from .hybrid_authority import SECTIONS as AUTHORITY, command_key, timestamp, _validate_approval
from .hybrid_goals import SECTIONS as GOALS, digest, draft_head, head_key, check_bytes
from .hybrid_protocol import ID, HASH, TIME, obj, array, enum, validate_schema
from .hybrid_registry import Registry
from .hybrid_snapshot import validate_manifest
from .store import Conflict, sha, canonical

SECTIONS = ('hybrid_preparation_intents', 'hybrid_preparation_results')
EVENTS = ('HYBRID_PREPARATION_INTENT', 'HYBRID_PREPARATION_RECORDED')
COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 2**63-1}
POSITIVE = {**COUNT, 'minimum': 1}
IDENTITY = {**array({'type': 'integer', 'minimum': 0, 'maximum': 2**64-1}, 2), 'minItems': 2}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
LOCATION = obj({'path': PATH, 'identity': IDENTITY})
PATHS = obj({'candidate': LOCATION, 'writes': array(LOCATION, 128)})
GATES = obj(dict.fromkeys(('source_authority', 'model_access', 'actual_data', 'os_resources',
                         'controller_lease', 'writer_lease', 'budget_reservation', 'stop_recovery'),
                        {'const': 'UNVERIFIED'}))
PLAN = obj({'schema_version': {'const': '1.0'}, 'adapter': {'const': 'codex-exec'},
            'packet': PACKET, 'profile': PROFILE, 'paths': PATHS, 'config_hash': HASH,
            'role_definition': {'type': 'object'}, 'result_schema': {'type': 'object'},
            'gates': GATES, 'execution_enabled': {'const': False}})
SNAPSHOT = obj({'schema_version': {'const': '1.0'}, 'files': {**array(obj({
    'name': PATH, 'bytes': {**COUNT, 'maximum': 256*1024**2},
    'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}, 'mode': {'const': 0o600},
    'source_executable': {'type': 'boolean'}}), 4096), 'minItems': 1},
    'total_bytes': {**COUNT, 'maximum': 256*1024**2}, 'tree_hash': HASH,
    'execution_enabled': {'const': False}})
MANIFEST = obj({'plan_hash': HASH, 'files': obj(dict.fromkeys(FILES, HASH)),
                'execution_enabled': {'const': False}})
SEAL = obj({'manifest_hash': HASH, 'manifest': MANIFEST,
            'directories': obj(dict.fromkeys(('', 'control', 'scratch'), IDENTITY)),
            'file_lengths': obj(dict.fromkeys(FILES, {**COUNT, 'maximum': 16*1024**2}))})
BUNDLE = obj({'schema_version': {'const': '1.0'}, 'plan_hash': HASH,
    'stage_name': {'type': 'string', 'pattern': '^\\.preparing-[A-Za-z0-9_-]{1,100}$'},
    'seal': SEAL, 'execution_enabled': {'const': False}})
SOURCES = obj({'schema_version': {'const': '1.0'}, 'project_id': ID, 'data_mode': enum('live', 'fixture'),
    'store_epoch': ID, 'source_version': COUNT, 'goal_ref': ID, 'contract_key': ID,
    'contract_revision': POSITIVE, 'proposal_hash': HASH, 'record_hash': HASH,
    'draft_command_key': ID, 'draft_source_version': POSITIVE, 'approval_key': ID,
    'approval_hash': HASH, 'authority_revision': POSITIVE, 'approval_command_key': ID,
    'approval_source_version': POSITIVE, 'config_hash': HASH, 'scope_hash': HASH,
    'evaluated_at': TIME, 'expires_at': TIME, 'execution_enabled': {'const': False}})
REQUEST = obj({'idempotency_key': ID, 'project_id': ID, 'data_mode': enum('live', 'fixture'),
               'goal_ref': ID, 'role': PACKET['properties']['role'], 'context': PACKET['properties']['context']})
MATERIAL = obj({'preparation_id': ID, 'plan_hash': HASH, 'manifest_hash': HASH,
                'execution_enabled': {'const': False}})
MATERIAL_OBSERVATION = obj({'witness_id':ID,'intent_key':ID,'intent_hash':HASH,
    'result_key':ID,'result_hash':HASH,'snapshot_id':ID,'snapshot_hash':HASH,
    'plan_hash':HASH,'manifest_hash':HASH,'checked_at':TIME,'expires_at':TIME,
    'state':{'const':'VERIFIED_AS_OF'},'execution_enabled':{'const':False}})
RECORDS = {
    SECTIONS[0]: obj({'request': REQUEST, 'request_hash': HASH, 'sources': SOURCES, 'plan': PLAN,
        'snapshot': SNAPSHOT, 'snapshot_id': ID, 'bundle': BUNDLE, 'created_at': TIME,
        'accepted_state_version': POSITIVE, 'state': {'const': 'INTENT'}, 'execution_enabled': {'const': False}}),
    SECTIONS[1]: obj({'intent_key': ID, 'intent_hash': HASH, 'status': enum('PREPARED', 'BLOCKED', 'UNKNOWN'),
        'reason': enum('MATERIAL_VERIFIED', 'SOURCE_CHANGED', 'MATERIAL_MISSING', 'MATERIAL_CHANGED', 'RECONCILE_UNKNOWN'),
        'material': {'oneOf': [MATERIAL, {'type': 'null'}]}, 'sources': {'oneOf': [SOURCES, {'type': 'null'}]},
        'recorded_at': TIME, 'expected_state_version': COUNT, 'accepted_state_version': POSITIVE,
        'execution_enabled': {'const': False}}),
}


def intent_key(request):
    return 'prepare_intent_'+sha([request['project_id'], request['data_mode'], request['idempotency_key']])


def result_key(intent_id):
    return 'prepare_result_'+sha(intent_id)


def source_binding(loaded):
    return {key: value for key, value in loaded.items() if key not in ('record', 'approval_fact')}


def validate_record(section, key, value):
    check_bytes(value, 4*1024**2); validate_schema(RECORDS[section], value)
    if section == SECTIONS[0]:
        request, sources, plan = value['request'], value['sources'], value['plan']
        snapshot, bundle = value['snapshot'], value['bundle']
        if key != intent_key(request) or value['request_hash'] != digest(request): raise Conflict('preparation intent identity differs')
        if (sources['source_version']+1 != value['accepted_state_version'] or
                value['created_at'] != sources['evaluated_at'] or
                any(request[name] != sources[name] for name in ('project_id', 'data_mode', 'goal_ref'))):
            raise Conflict('preparation intent source version differs')
        packet = plan['packet']; expected_packet = {'schema_version': '1.0',
            'project_id': sources['project_id'], 'data_mode': sources['data_mode'], 'store_epoch': sources['store_epoch'],
            'goal_id': packet['goal_id'], 'contract_revision': sources['contract_revision'],
            'proposal_hash': sources['proposal_hash'], 'approval_key': sources['approval_key'],
            'candidate_snapshot_hash': snapshot['tree_hash'], 'role': request['role'], 'context': request['context']}
        if (packet != expected_packet or sources['goal_ref'] != head_key(packet['project_id'], packet['data_mode'], packet['goal_id'])
                or plan['config_hash'] != sources['config_hash']): raise Conflict('preparation plan binding differs')
        names = []
        for row in snapshot['files']:
            names.append(row['name'])
            if type(row['bytes']) is not int or type(row['mode']) is not int: raise Conflict('actual snapshot integers required')
        validate_manifest(names)
        if len(canonical(packet)) > 256*1024: raise Conflict('preparation packet exceeds bound')
        if (names != sorted(set(names)) or snapshot['tree_hash'] != digest(snapshot['files']) or
                snapshot['total_bytes'] != sum(row['bytes'] for row in snapshot['files'])):
            raise Conflict('preparation snapshot descriptor differs')
        if (bundle['plan_hash'] != digest(plan) or bundle['seal']['manifest']['plan_hash'] != digest(plan)
                or bundle['seal']['manifest_hash'] != digest(bundle['seal']['manifest'])
                or sum(bundle['seal']['file_lengths'].values())+len(canonical(bundle['seal']['manifest'])) > 16*1024**2):
            raise Conflict('preparation expected seal differs')
        for filename, content in (('packet.json', packet), ('result.schema.json', plan['result_schema'])):
            if (bundle['seal']['manifest']['files'][filename] != digest(content) or
                    bundle['seal']['file_lengths'][filename] != len(canonical(content))):
                raise Conflict('preparation deterministic file seal differs')
        integers = [packet['contract_revision'], plan['profile']['memory_bytes'], plan['profile']['command_seconds'],
                    snapshot['total_bytes'], *bundle['seal']['file_lengths'].values()]
        integers.extend(v for identity in bundle['seal']['directories'].values() for v in identity)
        integers.extend(v for location in [plan['paths']['candidate'], *plan['paths']['writes']] for v in location['identity'])
        if any(type(v) is not int for v in integers): raise Conflict('actual preparation plan integers required')
    else:
        if key != result_key(value['intent_key']) or value['accepted_state_version'] != value['expected_state_version']+1:
            raise Conflict('preparation result identity differs')
        prepared = value['status'] == 'PREPARED'
        if (prepared != (value['material'] is not None) or prepared != (value['sources'] is not None)
                or prepared != (value['reason'] == 'MATERIAL_VERIFIED')):
            raise Conflict('preparation result status differs')
        timestamp(value['recorded_at'])
    for counter in ('accepted_state_version', 'expected_state_version'):
        if counter in value and type(value[counter]) is not int: raise Conflict('actual preparation integer required')
    sources = value['sources']
    if sources is not None:
        for counter in ('source_version', 'contract_revision', 'authority_revision', 'draft_source_version', 'approval_source_version'):
            if type(sources[counter]) is not int: raise Conflict('actual source integer required')
        if not sources['draft_source_version'] <= sources['approval_source_version'] <= sources['source_version']:
            raise Conflict('preparation original source order differs')
        if timestamp(sources['evaluated_at']) >= timestamp(sources['expires_at']): raise Conflict('preparation consent expired at capture')


def validate_persisted(state):
    for section in SECTIONS:
        for key, value in state.get(section, {}).items(): validate_record(section, key, value)


def _references(sources, lookup, *, current=False):
    record = lookup(GOALS[0], sources['contract_key']); fact = lookup(AUTHORITY[0], sources['approval_key'])
    if record is None or fact is None: raise Conflict('preparation original references missing')
    proposal = record['contract']['proposal']; confirm = fact['request']['confirmation']
    binding = Registry(fact['registry_witness']).resolve(proposal)
    _validate_approval(fact, lookup)
    draft_receipt = lookup(GOALS[2], sources['draft_command_key'])
    approval_receipt = lookup(AUTHORITY[3], sources['approval_command_key'])
    if (head_key(proposal['project_id'], proposal['data_mode'], proposal['goal_id']) != sources['goal_ref']
            or (proposal['project_id'], proposal['data_mode']) != (sources['project_id'], sources['data_mode'])
            or record.get('source_command_key') != sources['draft_command_key'] or digest(record) != sources['record_hash']
            or digest(fact) != sources['approval_hash'] or digest(proposal) != sources['proposal_hash']
            or proposal['contract_version'] != sources['contract_revision']
            or fact['authority_revision'] != sources['authority_revision']
            or command_key(fact['request']) != sources['approval_command_key']
            or confirm['store_epoch'] != sources['store_epoch']
            or fact['expires_at'] != sources['expires_at']
            or any(binding[name] != sources[name] for name in ('config_hash', 'scope_hash'))
            or draft_receipt is None or draft_receipt['accepted_state_version'] != sources['draft_source_version']
            or approval_receipt is None or approval_receipt['accepted_state_version'] != sources['approval_source_version']
            or timestamp(fact['approved_at']) > timestamp(sources['evaluated_at'])):
        raise Conflict('preparation original reference binding differs')
    if current:
        if lookup(GOALS[1], sources['goal_ref']) != draft_head(proposal): raise Conflict('preparation is not current draft')
        head = lookup(AUTHORITY[2], sources['goal_ref'])
        if head is None or head['state'] != 'LEASE_VALIDATION_PENDING' or head['approval_key'] != sources['approval_key']:
            raise Conflict('preparation is not current consent')
    return fact


def _intent_links(value, lookup, *, current=False):
    fact = _references(value['sources'], lookup, current=current)
    if value['plan']['profile'] != fact['registry_witness']['runtime_profile']:
        raise Conflict('preparation original runtime profile differs')


def _result_links(value, intent, lookup, *, current=False):
    if value['intent_hash'] != digest(intent) or intent['accepted_state_version'] >= value['accepted_state_version']:
        raise Conflict('preparation result intent predecessor differs')
    if timestamp(value['recorded_at']) < timestamp(intent['created_at']):
        raise Conflict('preparation result clock regressed')
    if value['status'] != 'PREPARED': return
    sources = value['sources']; _references(sources, lookup, current=current)
    if value['recorded_at'] != sources['evaluated_at'] or sources['source_version'] != value['expected_state_version']:
        raise Conflict('preparation result source version differs')
    previous = intent['sources']
    if any(sources[k] != previous[k] for k in previous if k not in ('source_version', 'evaluated_at')):
        raise Conflict('preparation result original context changed')
    if value['material'] != {'preparation_id': 'preparation_'+sha(intent['plan']),
        'plan_hash': intent['bundle']['plan_hash'], 'manifest_hash': intent['bundle']['seal']['manifest_hash'],
        'execution_enabled': False}: raise Conflict('preparation result material differs')


def validate_transition(payload, lookup, *, event_type, key, object_id, producer, version, registration):
    touched = event_type in EVENTS or any(
        isinstance(row, (list, tuple)) and row and row[0] in SECTIONS
        for field in ('put', 'delete') for row in payload.get(field, [])
    ) or set(payload.get('set', {})) & set(SECTIONS)
    if not touched: return
    if (set(payload) != {'format', 'put', 'delete', 'details'} or payload.get('format') != 2 or
            type(payload.get('put')) is not list or type(payload.get('delete')) is not list or payload['delete'] or
            any(type(row) is not list or len(row) != 3 or
                type(row[0]) is not str or type(row[1]) is not str for row in payload['put'])):
        raise Conflict('preparation requires append-only object transaction')
    rows = [(s,k,v) for s,k,v in payload['put'] if k]
    markers = [(s,v) for s,k,v in payload['put'] if not k]
    if (len(rows) != 1 or any(s not in SECTIONS or v != {} or lookup(s,'') is not None for s,v in markers)
            or len({s for s,v in markers}) != len(markers)):
        raise Conflict('preparation transaction shape differs')
    section, record_key, value = rows[0]
    if section not in SECTIONS or lookup(section, record_key) is not None: raise Conflict('immutable preparation record required')
    validate_record(section, record_key, value)
    if (event_type != EVENTS[SECTIONS.index(section)] or key != record_key or object_id != digest(value)
            or producer != 'hybrid-core' or value['accepted_state_version'] != version):
        raise Conflict('preparation event binding differs')
    if section == SECTIONS[0]:
        sources = value['sources']; _intent_links(value, lookup, current=True)
        if registration != (sources['project_id'], sources['data_mode']): raise Conflict('preparation registration differs')
    else:
        intent = lookup(SECTIONS[0], value['intent_key'])
        if intent is None: raise Conflict('preparation result intent missing')
        if registration != (intent['sources']['project_id'], intent['sources']['data_mode']): raise Conflict('preparation result registration differs')
        _result_links(value, intent, lookup, current=True)


def validate_complete(state, registration=None, event_lookup=None):
    validate_persisted(state)
    lookup = lambda section,key: state.get(section, {}).get(key)
    for section in SECTIONS:
        for key, value in state.get(section, {}).items():
            if value['accepted_state_version'] > state['version'] or event_lookup is None or event_lookup(key) != (
                    (EVENTS[SECTIONS.index(section)], 'hybrid-core', digest(value), value['accepted_state_version']),
                    [(section, key, digest(value))]):
                raise Conflict('preparation original event proof differs')
            if section == SECTIONS[0]:
                sources = value['sources']; _intent_links(value, lookup)
                if registration != (sources['project_id'], sources['data_mode']): raise Conflict('preparation historical registration differs')
            else:
                intent = lookup(SECTIONS[0], value['intent_key'])
                if intent is None: raise Conflict('preparation historical intent missing')
                _result_links(value, intent, lookup)
