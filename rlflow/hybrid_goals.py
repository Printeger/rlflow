"""Persistent unapproved Hybrid contracts, never execution authority.

The caller supplies a server-authenticated Principal, not a principal decoded
from request JSON. No approval, lease, dispatch or HTTP write route is enabled
here. Legacy package goals/approvals remain a separate authority domain.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .hybrid_protocol import (ID, HASH, COUNT, TIME, OBJECTS, ProtocolError,
                              obj, array, nullable, enum, validate, validate_schema)
from .store import sha, canonical, Conflict
from .web_auth import Principal

SECTIONS = ('hybrid_goal_contracts', 'hybrid_goal_heads', 'hybrid_goal_commands')
MAX_BYTES = 256 * 1024
ACTOR = obj({'id': ID, 'kind': enum('human', 'agent')})
PROPOSAL = deepcopy(OBJECTS['GoalContract']['properties']['proposal'])
REQUEST = obj({'action': {'const': 'propose_goal_draft'}, 'project_id': ID,
               'data_mode': enum('live', 'fixture'), 'actor': ACTOR,
               'idempotency_key': ID, 'expected_revision': COUNT, 'proposal': PROPOSAL})
# Optional only for compatibility with original immutable draft receipts.
# The future HTTP command version must require this field, never precheck only.
REQUEST['properties']['expected_state_version'] = {**COUNT, 'maximum': 2**63-1}
REQUEST['properties']['control_command_id'] = ID
DRAFT_CONTRACT = deepcopy(OBJECTS['GoalContract'])
DRAFT_CONTRACT['properties'].update(state={'const': 'DRAFT'}, approval_id={'type': 'null'}, outcome={'type': 'null'})
RECORDS = {
    SECTIONS[0]: obj({'contract': DRAFT_CONTRACT, 'previous_hash': nullable(HASH),
                     'changes': array(obj({'path': {'type': 'string', 'maxLength': 4000}, 'before': {}, 'after': {}}), 400),
                     'submitted_by': ACTOR, 'submitted_at': TIME}),
    SECTIONS[1]: obj({'project_id': ID, 'data_mode': enum('live', 'fixture'), 'goal_id': ID,
                     'revision': {'type': 'integer', 'minimum': 1}, 'contract_key': ID, 'contract_hash': HASH}),
    SECTIONS[2]: obj({'request': REQUEST, 'request_hash': HASH, 'contract_key': ID,
                     'contract_hash': HASH, 'accepted_state_version': {'type': 'integer', 'minimum': 1}}),
}


def digest(value):
    return 'sha256:' + sha(value)


def head_key(project_id, data_mode, goal_id):
    return 'goal_' + sha([project_id, data_mode, goal_id])


def revision_key(proposal):
    return 'contract_' + sha([proposal['project_id'], proposal['data_mode'], proposal['goal_id'], proposal['contract_version']])


def command_key(request):
    if 'control_command_id' in request:return request['control_command_id']
    return 'goal_command_' + sha([request['action'], request['actor'], request['project_id'], request['data_mode'], request['idempotency_key']])


def control_command_key(actor, project_id, data_mode, idempotency_key):
    """Shared HTTP namespace across actions; old internal keys stay immutable."""
    return 'control_' + sha([actor,project_id,data_mode,idempotency_key])


def bounded_copy(value):
    try:
        raw = canonical(value)
        if len(raw) > MAX_BYTES:raise ProtocolError('goal proposal exceeds bounded input')
        return json.loads(raw)
    except ProtocolError:raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProtocolError('invalid goal proposal JSON') from exc


def check_bytes(value, limit=MAX_BYTES):
    try:
        if len(canonical(value)) > limit:raise ProtocolError('goal proposal exceeds bounded input')
    except ProtocolError:raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProtocolError('invalid or oversized goal JSON') from exc


def validate_request(request):
    check_bytes(request)
    validate_schema(REQUEST, request)
    if 'expected_state_version' in request and type(request['expected_state_version']) is not int:
        raise ProtocolError('invalid expected state version')
    if ('control_command_id' in request and request['control_command_id']!=control_command_key(
            request['actor'],request['project_id'],request['data_mode'],request['idempotency_key'])):
        raise ProtocolError('control command identity mismatch')
    p = request['proposal']
    if type(request['expected_revision']) is not int or type(p['contract_version']) is not int or p['contract_version'] != request['expected_revision'] + 1:
        raise ProtocolError('contract revision must advance by one')
    if (p['project_id'], p['data_mode']) != (request['project_id'], request['data_mode']):
        raise ProtocolError('proposal differs from registered project', 'PERMISSION_DENIED')
    ids = [c['id'] for c in p['global_conditions']]
    if len(ids) > 200 or len(set(ids)) != len(ids) or not any(c['required'] for c in p['global_conditions']):
        raise ProtocolError('global conditions need unique IDs and a required condition')
    if p['scope']['network_access'] == 'none' and p['scope']['allowed_hosts']:
        raise ProtocolError('network-disabled proposal cannot name allowed hosts')
    if any(type(value) is not int or not 0 <= value <= 2**63-1 for name,value in p['budget'].items() if name not in ('model_token_enforcement','finalization_reserve_fraction')) or p['contract_version'] > 2**63-1:
        raise ProtocolError('goal integer exceeds storage bounds')
    for field in ('writable_paths', 'protected_paths'):
        paths = p['scope'][field]
        if len(paths) > 128 or len(set(paths)) != len(paths):raise ProtocolError('invalid declared path collection')
        for path in paths:
            if len(path) > 4000 or path in ('/', '.', '') or any(part in ('.', '..') for part in path.split('/')) or any(ord(c)<32 or ord(c)==127 for c in path) or any(c in path for c in ('\\', '*', '?', '[', ']')):
                raise ProtocolError('invalid declared path; filesystem scope is not yet approved')
    for field in ('allowed_hosts', 'allowed_command_templates'):
        values = p['scope'][field]
        if len(values) > 128 or len(set(values)) != len(values) or any(len(v) > 4000 for v in values):raise ProtocolError('invalid scope collection')
    if len(p['stop_rules']) > 100 or any(len(v) > 4000 for v in p['stop_rules']):raise ProtocolError('invalid stop rules')
    for condition in p['global_conditions']:
        verification = condition['verification']
        if len(condition['description']) > 4000 or len(verification['rule']) > 4000 or len(verification['evidence_required']) > 200 or any(len(v) > 4000 for v in verification['evidence_required']):
            raise ProtocolError('invalid bounded verification rule')
    if p['schema_version']=='1.1':
        datasets=p['evaluation_data']['datasets']
        if len({d['dataset_id'] for d in datasets})!=len(datasets):raise ProtocolError('dataset IDs must bind one version and access boundary')


def validate_record(section, key, record):
    check_bytes(record,4*MAX_BYTES)
    validate_schema(RECORDS[section], record)
    if section == SECTIONS[0]:
        c = record['contract'];validate('GoalContract', c)
        if key != revision_key(c['proposal']) or not record['submitted_at'].endswith('Z'):
            raise ProtocolError('draft record identity mismatch')
        if (c['version'] == 1) != (record['previous_hash'] is None):
            raise ProtocolError('draft revision predecessor mismatch')
    elif section == SECTIONS[1]:
        if key != head_key(record['project_id'], record['data_mode'], record['goal_id']):
            raise ProtocolError('draft head identity mismatch')
        p = {'project_id': record['project_id'], 'data_mode': record['data_mode'], 'goal_id': record['goal_id'], 'contract_version': record['revision']}
        if record['contract_key'] != revision_key(p):raise ProtocolError('draft head revision mismatch')
    else:
        request = record['request'];validate_request(request)
        if key != command_key(request) or record['request_hash'] != digest(request) or record['contract_key'] != revision_key(request['proposal']) or record['contract_hash'] != digest(request['proposal']):
            raise ProtocolError('draft receipt identity mismatch')
        if 'expected_state_version' in request and record['accepted_state_version'] != request['expected_state_version']+1:
            raise ProtocolError('draft receipt global version mismatch')


def validate_persisted(state):
    """Called by the existing runtime validator, including replay/recovery."""
    for section in SECTIONS:
        for key, record in state.get(section, {}).items():
            validate_record(section, key, record)


def validate_transition(payload, lookup, *, event_type, key, object_id, producer, version, registration):
    """The same transition gate protects live commits and historical replay."""
    if payload.get('format') != 2:
        if set(payload.get('set', {})) & set(SECTIONS):raise Conflict('Hybrid drafts require explicit object transaction')
        return
    puts = {(s, k): v for s, k, v in payload['put'] if s in SECTIONS and k}
    markers = [(s, v) for s, k, v in payload['put'] if s in SECTIONS and not k]
    if any(s in SECTIONS for s, k in payload['delete']):raise Conflict('Hybrid draft records cannot be deleted')
    if not puts and not markers:return
    if any(lookup(section,'') is not None for section,value in markers):raise Conflict('existing draft collection marker cannot be rewritten')
    if event_type != 'HYBRID_GOAL_DRAFTED' or producer != 'hybrid-core' or len(puts) != 3 or len(puts)+len(markers)!=len(payload['put']) or len({s for s,v in markers})!=len(markers) or any(v != {} for s, v in markers):
        raise Conflict('invalid Hybrid draft transition')
    if any(s not in SECTIONS for s,k,v in payload['put']) or payload['delete']:
        raise Conflict('draft command cannot mutate legacy authority or control')
    rows = {}
    for section in SECTIONS:
        found = [(k, v) for (s, k), v in puts.items() if s == section]
        if len(found) != 1:raise Conflict('draft transition requires contract, head and receipt')
        rk, record = found[0];validate_record(section, rk, record);rows[section] = (rk, record)
    rk, record = rows[SECTIONS[0]];hk, head = rows[SECTIONS[1]];ck, receipt = rows[SECTIONS[2]]
    request = receipt['request'];p = request['proposal'];c = record['contract']
    if registration != (request['project_id'], request['data_mode']):raise Conflict('draft registration changed or missing')
    if key != ck or object_id != receipt['request_hash'] or receipt['accepted_state_version'] != version:
        raise Conflict('draft event/receipt mismatch')
    if c['proposal'] != p or record['submitted_by'] != request['actor'] or receipt['contract_key'] != rk or receipt['contract_hash'] != c['hash']:
        raise Conflict('draft contract/receipt mismatch')
    if hk != head_key(p['project_id'], p['data_mode'], p['goal_id']) or head['contract_key'] != rk or head['contract_hash'] != c['hash']:
        raise Conflict('draft contract/head mismatch')
    if lookup(SECTIONS[0], rk) is not None or lookup(SECTIONS[2], ck) is not None:
        raise Conflict('draft revisions and receipts are immutable')
    old_head = lookup(SECTIONS[1], hk);expected = request['expected_revision']
    if old_head is not None:validate_record(SECTIONS[1],hk,old_head)
    if (old_head['revision'] if old_head else 0) != expected:raise Conflict('stale goal revision')
    old = lookup(SECTIONS[0], revision_key({**p, 'contract_version': expected})) if expected else None
    if expected and (old is None or old_head['contract_hash'] != old['contract']['hash']):raise Conflict('draft predecessor missing or corrupt')
    previous_hash = old['contract']['hash'] if old else None
    changes = differences(old['contract']['proposal'], p) if old else []
    if record['previous_hash'] != previous_hash or record['changes'] != changes:raise Conflict('draft predecessor/diff mismatch')


def validate_complete(state, registration=None, event_lookup=None):
    """Cross-object closure for full snapshots/recovery, never a partial write."""
    validate_persisted(state)
    contracts = state.get(SECTIONS[0], {});heads = state.get(SECTIONS[1], {});commands = state.get(SECTIONS[2], {})
    latest = {};covered = set()
    for rk, record in contracts.items():
        c = record['contract'];p = c['proposal'];hk = head_key(p['project_id'], p['data_mode'], p['goal_id'])
        if registration != (p['project_id'], p['data_mode']):raise Conflict('snapshot draft registration mismatch')
        if hk not in latest or c['version'] > latest[hk]['contract']['version']:latest[hk] = record
        old = contracts.get(revision_key({**p, 'contract_version': c['version'] - 1})) if c['version'] > 1 else None
        if c['version'] > 1 and old is None:raise Conflict('draft predecessor missing')
        if record['previous_hash'] != (old['contract']['hash'] if old else None) or record['changes'] != (differences(old['contract']['proposal'], p) if old else []):
            raise Conflict('draft historical diff mismatch')
    if set(heads) != set(latest):raise Conflict('draft heads do not cover contracts')
    for hk, head in heads.items():
        c = latest[hk]['contract']
        if head['contract_key'] != revision_key(c['proposal']) or head['contract_hash'] != c['hash'] or head['revision'] != c['version']:raise Conflict('draft head is not latest revision')
    for ck,receipt in commands.items():
        rk = receipt['contract_key'];record = contracts.get(rk)
        if record is None or receipt['request']['proposal'] != record['contract']['proposal'] or receipt['request']['actor'] != record['submitted_by'] or receipt['accepted_state_version'] > state['version']:
            raise Conflict('draft receipt does not match contract')
        if rk in covered:raise Conflict('draft revision has duplicate receipts')
        expected=('HYBRID_GOAL_DRAFTED','hybrid-core',receipt['request_hash'],receipt['accepted_state_version'])
        if event_lookup is None or event_lookup(ck)!=expected:raise Conflict('draft receipt does not match original core event')
        covered.add(rk)
    if covered != set(contracts):raise Conflict('draft revision lacks receipt')


def differences(before, after, path=''):
    """Explicit JSON-pointer leaf differences; arrays are whole-field changes."""
    rows = []
    for key in sorted(set(before) | set(after)):
        pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
        old, new = before.get(key), after.get(key)
        if old == new:continue
        if isinstance(old, dict) and isinstance(new, dict):rows.extend(differences(old, new, pointer))
        else:rows.append({'path': pointer, 'before': old, 'after': new})
    return rows


def propose(store, proposal, *, principal, project_id, data_mode, idempotency_key, expected_revision,
            expected_state_version=None, _authorization=None, _control_command_id=None):
    """Create an immutable draft revision + CAS head + original receipt atomically.

    project_id/data_mode come from trusted core registration. No missing tools
    or evaluation-data fields are interpreted as permission: all records are
    DRAFT with approval_id=None, and cannot be executed by this module.
    """
    if not isinstance(principal, Principal) or not principal.allows(project_id, 'operator'):
        raise ProtocolError('goal proposal requires scoped operator', 'PERMISSION_DENIED')
    from .observation import ObservationReader
    try:head = ObservationReader(store.root).head()
    except ProtocolError as error:
        if _authorization is not None:raise Conflict('draft observation source unavailable') from error
        raise
    if (head['project_id'], head['data_mode']) != (project_id, data_mode):
        raise ProtocolError('store differs from registered project', 'PERMISSION_DENIED')
    request = {'action': 'propose_goal_draft', 'project_id': project_id, 'data_mode': data_mode,
        'actor': {'id': principal.id, 'kind': principal.kind}, 'idempotency_key': idempotency_key,
        'expected_revision': expected_revision, 'proposal': proposal}
    if expected_state_version is not None:request['expected_state_version']=expected_state_version
    if _control_command_id is not None:request['control_command_id']=_control_command_id
    request = bounded_copy(request)
    validate_request(request)
    p = request['proposal'];request_hash = digest(request);ck = command_key(request);rk = revision_key(p)
    hk = head_key(project_id, data_mode, p['goal_id'])
    previous_key = revision_key({**p, 'contract_version': expected_revision}) if expected_revision else None
    selected = [(SECTIONS[0], rk), (SECTIONS[1], hk), (SECTIONS[2], ck)]
    if previous_key:selected.append((SECTIONS[0], previous_key))
    def change(state):
        old_head = state.setdefault(SECTIONS[1], {}).get(hk)
        if old_head is not None:validate_record(SECTIONS[1],hk,old_head)
        if (old_head['revision'] if old_head else 0) != expected_revision:raise Conflict('stale goal revision')
        contracts = state.setdefault(SECTIONS[0], {})
        if rk in contracts:raise Conflict('contract revision is immutable')
        old = contracts.get(previous_key) if previous_key else None
        if previous_key and (old is None or old_head['contract_hash'] != old['contract']['hash']):raise Conflict('draft predecessor missing or corrupt')
        contract = {'id': p['goal_id'], 'version': p['contract_version'], 'hash': digest(p), 'proposal': p,
                    'state': 'DRAFT', 'approval_id': None, 'outcome': None}
        contracts[rk] = {'contract': contract, 'previous_hash': old['contract']['hash'] if old else None,
            'changes': differences(old['contract']['proposal'], p) if old else [], 'submitted_by': request['actor'],
            'submitted_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}
        state[SECTIONS[1]][hk] = {'project_id': project_id, 'data_mode': data_mode, 'goal_id': p['goal_id'],
            'revision': p['contract_version'], 'contract_key': rk, 'contract_hash': contract['hash']}
        state.setdefault(SECTIONS[2], {})[ck] = {'request': request, 'request_hash': request_hash,
            'contract_key': rk, 'contract_hash': contract['hash'], 'accepted_state_version': state['version'] + 1}
        return {'contract_key': rk, 'request_hash': request_hash}
    kwargs={'expected':expected_state_version,'object_id':request_hash,'producer':'hybrid-core'}
    if _authorization is not None:kwargs['_authorization']=_authorization
    result = store.transact_objects('HYBRID_GOAL_DRAFTED', ck, selected, change, **kwargs)
    # Store's duplicate branch returns the *current* state version. Only the
    # immutable original receipt determines the response of a retried command.
    with store.connect() as db:
        db.execute('BEGIN')
        def read(section, key):
            row=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,key)).fetchone()
            return store._decode_value(db,json.loads(row[0])) if row else None
        receipt=read(SECTIONS[2],ck);record=read(SECTIONS[0],rk)
        event=store._goal_event(db,ck)
        if receipt is None or record is None or event is None:raise Conflict('draft command receipt or contract missing')
        validate_record(SECTIONS[2], ck, receipt);validate_record(SECTIONS[0], rk, record)
        if (store._goal_registration(db)!=(project_id,data_mode) or event!=('HYBRID_GOAL_DRAFTED','hybrid-core',request_hash,receipt['accepted_state_version']) or receipt['request_hash']!=request_hash or receipt['contract_hash']!=record['contract']['hash']):
            raise Conflict('draft command receipt mismatch')
    return {'contract': record['contract'], 'accepted_state_version': receipt['accepted_state_version'], 'duplicate': result['duplicate']}
