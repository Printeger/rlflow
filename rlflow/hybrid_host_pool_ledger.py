"""Closed fixture host-pool facts. Data never restores a live slot capability."""
import json
import math
import re

from .hybrid_goals import digest
from .hybrid_protocol import ID, validate_schema
from .hybrid_runtime_boundary import _path, _chain_value
from .store import Conflict, canonical, sha

CAPACITY = 3
MAX_EVENTS = 4096
MAX_BYTES = 16384
RUNTIME_ACTIONS = {'FIXTURE_LINKED', 'FIXTURE_HANDOFF_UNKNOWN', 'FIXTURE_STOP_REQUESTED',
                   'FIXTURE_STOPPED', 'FIXTURE_FREE'}
RETIRE = 'LOCAL_CPU_PHYSICALLY_RETIRED'
AVAILABLE = {'FREE', RETIRE}
ACTIONS = {'REGISTER', 'CLAIM', 'UNKNOWN', 'CLOSE_INTENT', 'FREE', RETIRE} | RUNTIME_ACTIONS


def closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise Conflict('closed host pool record required')


def count(value, minimum=0):
    if type(value) is not int or not minimum <= value < 2**63:
        raise Conflict('actual bounded host pool integer required')


def identifier(value):
    validate_schema(ID, value)


def pair(value):
    if type(value) is not list or len(value) != 2:
        raise Conflict('original host pool file identity required')
    for number in value: count(number)


def process(value):
    closed(value, ('pid', 'pgid', 'starttime', 'boot_id'))
    count(value['pid'], 1); count(value['pgid'], 1)
    if (type(value['starttime']) is not str or not re.fullmatch('[0-9]{1,20}', value['starttime']) or
            type(value['boot_id']) is not str or not re.fullmatch('[0-9a-f-]{36}', value['boot_id'])):
        raise Conflict('original host pool process identity required')


def member(value):
    closed(value, ('member_id', 'project_id', 'data_mode', 'store_epoch', 'store_root',
                   'store_chain', 'runtime_chain', 'db_identity', 'writer_identity', 'bootstrap'))
    for name in ('member_id', 'project_id', 'store_epoch'): identifier(value[name])
    if value['data_mode'] != 'fixture': raise Conflict('fixture pool membership only')
    root = _path(value['store_root']); _chain_value(value['store_chain'], root)
    _chain_value(value['runtime_chain'], root / 'runtime')
    pair(value['db_identity']); pair(value['writer_identity'])
    ref = value['bootstrap']
    closed(ref, ('intent_key', 'intent_hash', 'publication_key', 'publication_hash', 'expected_seal_hash',
                 'project_id', 'data_mode', 'store_epoch', 'installation_id', 'release_id'))
    for name in ('intent_key', 'publication_key', 'installation_id'): identifier(ref[name])
    for name in ('intent_hash', 'publication_hash', 'expected_seal_hash'):
        if type(ref[name]) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', ref[name]):
            raise Conflict('original pool bootstrap hash required')
    if (ref['project_id'], ref['data_mode'], ref['store_epoch']) != (
            value['project_id'], 'fixture', value['store_epoch']):
        raise Conflict('pool membership bootstrap scope differs')
    if type(ref['release_id']) is not str or not re.fullmatch('[0-9a-f]{64}', ref['release_id']):
        raise Conflict('original pool release identity required')
    expected = 'member_' + sha({k: v for k, v in value.items() if k != 'member_id'})
    if value['member_id'] != expected: raise Conflict('pool membership identity differs')


def validate(value):
    closed(value, ('pool_id', 'action', 'key', 'version', 'slot', 'payload'))
    if len(canonical(value)) > MAX_BYTES: raise Conflict('host pool fact exceeds finite byte bound')
    identifier(value['pool_id']); identifier(value['key']); count(value['version'], 1)
    action = value['action']; payload = value['payload']
    if action not in ACTIONS: raise Conflict('unknown host pool action')
    if action == 'REGISTER':
        if value['slot'] is not None: raise Conflict('pool registration cannot occupy a slot')
        member(payload)
    else:
        count(value['slot'])
        if value['slot'] >= CAPACITY: raise Conflict('host pool slot outside fixed capacity')
        if action == 'CLAIM':
            closed(payload, ('claim_id', 'member_id', 'owner', 'recorded_wall', 'recorded_mono',
                             'deadline_wall', 'deadline_mono', 'prior_key'))
            identifier(payload['claim_id']); identifier(payload['member_id']); process(payload['owner'])
            if payload['prior_key'] is not None: identifier(payload['prior_key'])
            for name in ('recorded_wall', 'recorded_mono', 'deadline_wall', 'deadline_mono'):
                number = payload[name]
                if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                    raise Conflict('finite pool clock required')
            for clock in ('wall', 'mono'):
                if not 0 < payload['deadline_' + clock] - payload['recorded_' + clock] <= 60:
                    raise Conflict('pool claim finite deadline required')
        else:
            names = ('claim_key', 'claim_hash', 'prior_key')
            if action in RUNTIME_ACTIONS or action == RETIRE:
                names += ('runtime_lease_id', 'project_fact_key', 'project_fact_hash')
                if action == 'FIXTURE_FREE': names += ('close_witness_hash',)
                if action == RETIRE: names += ('reservation_id', 'physical_proof_hash', 'signed_report', 'recovery_owner')
            if action == 'UNKNOWN': names += ('reason',)
            if action == 'FREE': names += ('close_witness_hash',)
            closed(payload, names)
            identifier(payload['claim_key']); identifier(payload['prior_key'])
            if action in RUNTIME_ACTIONS or action == RETIRE:
                identifier(payload['runtime_lease_id']); identifier(payload['project_fact_key'])
                if type(payload['project_fact_hash']) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', payload['project_fact_hash']):
                    raise Conflict('fixture runtime original project source digest required')
            if action == RETIRE:
                identifier(payload['reservation_id'])
                process(payload['recovery_owner'])
                from .hybrid_local_cpu_recovery import REPORT
                validate_schema(REPORT,payload['signed_report'])
                if payload['signed_report']['format'] != 'local_cpu_recovery/2':
                    raise Conflict('physical retirement requires original v2 signed scope')
                if type(payload['physical_proof_hash']) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', payload['physical_proof_hash']):
                    raise Conflict('original physical retirement proof digest required')
            if type(payload['claim_hash']) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', payload['claim_hash']):
                raise Conflict('original pool claim digest required')
            if action == 'UNKNOWN' and payload['reason'] not in ('OWNER_REQUESTED_UNKNOWN', 'REGISTRATION_PENDING'):
                raise Conflict('closed pool unknown reason required')
            if action in ('FREE', 'FIXTURE_FREE') and (type(payload['close_witness_hash']) is not str or
                    not re.fullmatch('sha256:[0-9a-f]{64}', payload['close_witness_hash'])):
                raise Conflict('original closed slot witness digest required')
    return value


def parse(raw):
    if type(raw) is not str or len(raw.encode()) > MAX_BYTES:
        raise Conflict('bounded literal host pool fact required')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise Conflict('duplicate host pool JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Conflict('nonfinite pool JSON')))
        if canonical(value).decode() != raw: raise Conflict('canonical host pool fact required')
    except (ValueError, TypeError, RecursionError) as error:
        raise Conflict('invalid bounded host pool fact') from error
    return validate(value)


def head(value):
    if value['action'] == 'REGISTER': return None
    return {'key': value['key'], 'version': value['version'], 'state': 'FREE' if value['action'] == 'FIXTURE_FREE' else value['action'],
            'claim_key': value['key'] if value['action'] == 'CLAIM' else value['payload']['claim_key']}


def links(value, lookup, members, *, current=None):
    """Bounded fixed-depth immutable proof; never walk all previous slot cycles."""
    validate(value)
    action = value['action']; payload = value['payload']
    if action == 'REGISTER': return
    if action == 'CLAIM':
        registration = members(payload['member_id'])
        if registration is None or registration['action'] != 'REGISTER':
            raise Conflict('original registered pool membership missing')
        if registration['pool_id'] != value['pool_id']: raise Conflict('pool membership source differs')
        if registration['version'] >= value['version']: raise Conflict('pool member source is not prior')
        prior = lookup(payload['prior_key']) if payload['prior_key'] is not None else None
        if payload['prior_key'] is not None and prior is None:
            raise Conflict('original prior FREE pool fact missing')
        if prior is not None and (prior['pool_id'] != value['pool_id'] or prior['action'] not in ('FREE', 'FIXTURE_FREE', RETIRE) or prior['slot'] != value['slot'] or
                                  prior['version'] >= value['version']):
            raise Conflict('pool claim cannot reuse occupied slot')
    else:
        claim = lookup(payload['claim_key']); prior = lookup(payload['prior_key'])
        if (claim is None or claim['action'] != 'CLAIM' or digest(claim) != payload['claim_hash'] or
                claim['pool_id'] != value['pool_id'] or prior is None or prior['pool_id'] != value['pool_id'] or
                prior['slot'] != value['slot'] or claim['slot'] != value['slot'] or
                prior['version'] >= value['version'] or
                head(prior)['claim_key'] != claim['key']):
            raise Conflict('host pool original claim lineage differs')
        allowed = {'UNKNOWN': {'CLAIM'}, 'CLOSE_INTENT': {'CLAIM', 'UNKNOWN'}, 'FREE': {'CLOSE_INTENT'},
            'FIXTURE_LINKED': {'CLAIM'}, 'FIXTURE_HANDOFF_UNKNOWN': {'FIXTURE_LINKED'},
            'FIXTURE_STOP_REQUESTED': {'CLAIM', 'FIXTURE_LINKED', 'FIXTURE_HANDOFF_UNKNOWN'},
            'FIXTURE_STOPPED': {'FIXTURE_STOP_REQUESTED'}, 'FIXTURE_FREE': {'FIXTURE_STOPPED'},
            RETIRE: {'FIXTURE_LINKED', 'FIXTURE_HANDOFF_UNKNOWN', 'FIXTURE_STOP_REQUESTED'}}[action]
        if prior['action'] not in allowed: raise Conflict('host pool no-handoff transition refused')
        if (action in RUNTIME_ACTIONS or action == RETIRE) and prior['action'] in RUNTIME_ACTIONS and prior['payload']['runtime_lease_id'] != payload['runtime_lease_id']:
            raise Conflict('fixture pool original runtime lease lineage changed')
    if current is not None:
        if action == 'CLAIM':
            if current['state'] not in AVAILABLE or current['key'] != payload['prior_key']:
                raise Conflict('pool slot is not actually FREE')
        elif current != head(lookup(payload['prior_key'])):
            raise Conflict('host pool stale prior slot head')
