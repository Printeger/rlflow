"""Suggestions for the explicitly captured finite scope, never Goal STOP."""
import json

from .hybrid_goals import bounded_copy, digest
from .hybrid_protocol import ID, HASH, obj, validate_schema, ProtocolError
from .store import Conflict, canonical
from .hybrid_control import ControlError

ACTION = 'request_finite_stop'
STOP_ACTION = 'CANCEL_ORIGINAL_FINITE_UNITS'
ACTOR = obj({'id': ID, 'kind': {'enum': ['agent', 'human']}})
ITEM = obj({'project_id': ID, 'data_mode': {'const': 'fixture'}, 'store_epoch': ID,
            'task_id': ID, 'stop_action': {'enum': ['CANCEL_FIXED_CPU_TRIAL', 'CANCEL_FIXED_ENGINEERING']}})
SCOPE = obj({'scope_sha256': HASH, 'items': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': ITEM}})
BODY = obj({'schema_version': {'const': '1.0'}, 'action': {'const': ACTION},
    'project_id': ID, 'data_mode': {'const': 'fixture'}, 'store_epoch': ID,
    'actor': ACTOR, 'idempotency_key': ID, 'stop_scope': SCOPE})
CLAIM = obj({'schema_version': {'const': '1.0'}, 'action': {'const': 'forward_finite_stop'},
    'actor': ACTOR, 'idempotency_key': ID, 'request_hash': HASH,
    'stop_scope': SCOPE, 'command_id': ID})
INTENT = obj({'schema_version': {'const': '1.1'}, 'command_id': ID,
    'action': ITEM['properties']['stop_action'], 'status': {'const': 'ACCEPTED'},
    'accepted_state_version': {'type': 'integer', 'minimum': 1, 'maximum': 2**63-1},
    'request_hash': HASH, 'actor_id': ID, 'task_id': ID, 'recorded_phase': {'const': 'STOP_INTENT_ACCEPTED'},
    'execution_status': {'const': 'UNKNOWN'}, 'native_execution_enabled': {'const': False},
    'arbitrary_tree_stop': {'const': False}, 'duplicate': {'type': 'boolean'}})
RESULT_ITEM = obj({'project_id': ID, 'store_epoch': ID, 'task_id': ID,
    'intent': {'anyOf': [INTENT, {'type': 'null'}]}, 'intent_status': {'enum': ['ACCEPTED','UNKNOWN']},
    'cleanup_status': {'enum': ['ORIGINAL_SCOPE_STOPPED','UNKNOWN']}, 'post_cleanup_status': {'enum': ['RETURNED','UNKNOWN']},
    'error_type': {'anyOf': [ID, {'type': 'null'}]}, 'goal_completed': {'const': False},
    'independent_review_status': {'const': 'NOT_PERFORMED'}})
RESULT = obj({'schema_version': {'const': '1.1'}, 'command_id': ID, 'action': {'const': STOP_ACTION},
    'duplicate': {'type': 'boolean'}, 'status': {'enum': ['ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN','PARTIAL_OR_UNKNOWN']},
    'scope': {'const': 'ORIGINAL_FIXED_BOUND_UNITS_ONLY'}, 'durable_aggregate_receipt': {'const': False},
    'cleanup_resume': {'type': 'boolean'}, 'items': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': RESULT_ITEM},
    'goal_completed': {'const': False}, 'independent_review_status': {'const': 'NOT_PERFORMED'}})
PUBLIC = obj({'schema_version': {'const': '1.0'}, 'request_id': ID, 'project_id': ID,
    'data_mode': {'const': 'fixture'}, 'store_epoch': ID, 'action': {'const': ACTION},
    'request_hash': HASH, 'submitted_by': ACTOR,
    'status': {'enum': ['AWAITING_HUMAN','UNKNOWN','STOPPED_AS_OF_RETURN','PARTIAL_OR_UNKNOWN']},
    'execution_enabled': {'const': False}, 'stop_scope': SCOPE,
    'result': {'anyOf': [RESULT, {'type': 'null'}]}})


def validate_public(value, project_id):
    import re
    from .hybrid_fixture_runtime_ledger import control_command_id
    validate_schema(PUBLIC, value); validate_scope(value['stop_scope'])
    if (value['project_id'] != project_id or value['submitted_by']['kind'] != 'agent' or
            re.fullmatch(r'request_[0-9a-f]{64}', value['request_id']) is None or
            re.fullmatch(r'store_[0-9a-f]{32}', value['store_epoch']) is None or
            not any((r['project_id'],r['store_epoch'])==(project_id,value['store_epoch']) for r in value['stop_scope']['items'])):
        raise ProtocolError('closed scoped finite request receipt required')
    result = value['result']
    if result is None:
        if value['status'] not in ('AWAITING_HUMAN','UNKNOWN'):
            raise ProtocolError('unproved finite cleanup cannot be success')
        return value
    if value['status'] not in ('STOPPED_AS_OF_RETURN','PARTIAL_OR_UNKNOWN') or len(result['items'])!=len(value['stop_scope']['items']):
        raise ProtocolError('finite result shape/status differs')
    actors=set();key='forward_'+value['request_id'][8:]
    for row, target in zip(result['items'],value['stop_scope']['items']):
        if any(row[k]!=target[k] for k in ('project_id','store_epoch','task_id')):
            raise ProtocolError('finite result original scope differs')
        receipt=row['intent']
        if receipt is None:
            if row['intent_status']!='UNKNOWN':raise ProtocolError('missing finite intent')
        else:
            actor=receipt['actor_id'];actors.add(actor)
            if (row['intent_status']!='ACCEPTED' or receipt['action']!=target['stop_action'] or receipt['task_id']!=target['task_id'] or
                    receipt['request_hash']!=digest({'action':target['stop_action'],'task_id':target['task_id']}) or
                    receipt['command_id']!=control_command_id(target,actor,key)):
                raise ProtocolError('finite intent original command differs')
    complete=all(r['intent_status']=='ACCEPTED' and r['cleanup_status']=='ORIGINAL_SCOPE_STOPPED' and r['post_cleanup_status']=='RETURNED' for r in result['items'])
    if (len(actors)>1 or complete!=(result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN') or
            complete!=(value['status']=='STOPPED_AS_OF_RETURN') or
            re.fullmatch(r'finite_stop_[0-9a-f]{64}',result['command_id']) is None or
            actors and result['command_id']!=command_id(value['stop_scope'],{'id':next(iter(actors))},key)):
        raise ProtocolError('finite aggregate identity/result differs')
    return value


def validate_scope(value):
    validate_schema(SCOPE, value)
    items = value['items']
    if ([r['project_id'] for r in items] != sorted({r['project_id'] for r in items}) or
            value['scope_sha256'] != digest([[r['project_id'], r['store_epoch'], r['task_id'], r['stop_action']] for r in items])):
        raise ProtocolError('explicit exact ordered original finite scope required')
    return value


def command_id(scope, actor, key):
    return 'finite_stop_' + digest([scope['scope_sha256'], actor['id'], key]).removeprefix('sha256:')


def decode(inbox, value, claim, rid):
    validate_schema(BODY, value); validate_scope(value['stop_scope'])
    if (value['actor']['kind'] != 'agent' or
            (value['project_id'], value['data_mode'], value['store_epoch']) !=
            (inbox.project_id, inbox.data_mode, inbox.store_epoch) or inbox._id(value) != rid or
            not any((r['project_id'], r['store_epoch']) == (inbox.project_id, inbox.store_epoch) for r in value['stop_scope']['items'])):
        raise Conflict('finite request anchor/identity differs')
    if claim is not None:
        validate_schema(CLAIM, claim)
        key = 'forward_' + rid[8:]
        if (claim['actor']['kind'] != 'human' or claim['idempotency_key'] != key or
                claim['request_hash'] != digest(value) or claim['stop_scope'] != value['stop_scope'] or
                claim['command_id'] != command_id(value['stop_scope'], claim['actor'], key)):
            raise Conflict('finite forwarding immutable claim differs')
    return value, claim


def allowed(principal, value, *, human=False):
    role = 'operator' if human else 'viewer'
    return all(principal.allows(r['project_id'], role) for r in value['stop_scope']['items'])


def dto(inbox, rid, value, claim, *, private=False):
    result = None
    if claim is not None and inbox.stop_requests is not None:
        result = inbox.stop_requests.source(claim)
    status = 'AWAITING_HUMAN' if claim is None else 'UNKNOWN' if result is None else (
        'STOPPED_AS_OF_RETURN' if result['status'] == 'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN' else 'PARTIAL_OR_UNKNOWN')
    out = {'schema_version': '1.0', 'request_id': rid, 'project_id': inbox.project_id,
        'data_mode': inbox.data_mode, 'store_epoch': inbox.store_epoch, 'action': ACTION,
        'request_hash': digest(value), 'submitted_by': value['actor'], 'status': status,
        'execution_enabled': False, 'stop_scope': value['stop_scope'], 'result': result}
    if private:
        out['forwarded_by'] = None if claim is None else claim['actor']
        out['original_owner_available'] = inbox.stop_requests is not None and inbox.stop_requests.available()
    return out


class FiniteStopRequests:
    """No own executor, STOP authority, result cache, or cold adoption."""
    def __init__(self, inbox, coordinator):
        from .hybrid_finite_host_stop import FiniteHostStop
        if type(coordinator) is not FiniteHostStop:
            raise TypeError('actual original finite coordinator required')
        coordinator._pure()
        if (inbox.data_mode != 'fixture' or coordinator.auth is not inbox.auth or coordinator.origin != inbox.origin or
                not any(s.store is inbox.store for s in coordinator.controls)):
            raise ValueError('original finite inbox binding differs')
        self.inbox, self.coordinator = inbox, coordinator
        self._inbox = inbox
        self._binding = (inbox.store, inbox.auth, inbox.project_id, inbox.data_mode, inbox.store_epoch, inbox.origin)
        self._coordinator = coordinator
        self._scope = {'scope_sha256': coordinator._scope, 'items': [
            {'project_id': p, 'data_mode': 'fixture', 'store_epoch': e, 'task_id': t, 'stop_action': a}
            for p, e, t, a, *_ in coordinator._signature]}
        self._raw = canonical(self._scope)
        validate_scope(self._scope)

    def identity(self):
        self._coordinator._parent_identity()  # Before inherited locks.
        inbox = self.inbox
        if (self.coordinator is not self._coordinator or canonical(self._scope) != self._raw or
                inbox is not self._inbox or inbox.stop_requests is not self or inbox._stop_requests is not self or
                (inbox.store, inbox.auth, inbox.project_id, inbox.data_mode, inbox.store_epoch, inbox.origin) != self._binding):
            raise PermissionError('original finite request binding required')

    def available(self):
        self.identity()
        try:
            self.coordinator._pure()
            return not self.coordinator._closed
        except PermissionError:
            return False

    def exact(self, scope):
        self.identity(); validate_scope(scope)
        if canonical(scope) != self._raw:
            from .hybrid_agent_requests import RequestConflict
            raise RequestConflict('explicit finite request scope changed')

    def source(self, claim):
        self.identity(); self.exact(claim['stop_scope'])
        # A missing/closed owner cannot reconstruct physical cleanup from a
        # durable human intent. Historical owner cache is not a current probe.
        if not self.available():
            return None
        return self.coordinator.read_result(claim['command_id'], actor_id=claim['actor']['id'])

    def submit(self, scope, *, token, key):
        inbox = self.inbox
        inbox._identity(); self.exact(scope)
        if not self.available():
            raise Conflict('original finite owner unavailable')
        with inbox._db(write=True) as db:
            with inbox.auth.request_guard(token, project_id=inbox.project_id) as check:
                principal = check().principal
                value = bounded_copy({'schema_version': '1.0', 'action': ACTION,
                    'project_id': inbox.project_id, 'data_mode': inbox.data_mode, 'store_epoch': inbox.store_epoch,
                    'actor': {'id': principal.id, 'kind': 'agent'}, 'idempotency_key': key, 'stop_scope': scope})
                rid = inbox._id(value); decode(inbox, value, None, rid)
                if not allowed(principal, value):
                    raise PermissionError('all original finite projects required')
                row = inbox._rows(db, rid=rid)
                if row is not None:
                    old, _ = inbox._decode(row)
                    if old != value:
                        from .hybrid_agent_requests import RequestConflict
                        raise RequestConflict('finite request idempotency key reused')
                else:
                    from .hybrid_agent_requests import MAX_ROWS
                    if db.execute('SELECT count(*) FROM requests').fetchone()[0] >= MAX_ROWS:
                        raise Conflict('bounded request inbox full')
                    db.execute('INSERT INTO requests(id,body) VALUES(?,?)', (rid, canonical(value).decode()))
                inbox._pure(); self.exact(value['stop_scope'])
                if not allowed(check().principal, value):
                    raise PermissionError('all finite projects still required')
                db.commit()
        return inbox.get(rid, token=token, method='request')

    def prepare(self, rid, *, request_hash, token, csrf, origin, resume_cleanup=False):
        from .hybrid_agent_requests import RequestConflict
        inbox = self.inbox
        inbox._identity(); self.identity()
        validate_schema(ID, rid); validate_schema(HASH, request_hash)
        if origin != inbox.origin or type(resume_cleanup) is not bool:
            raise PermissionError('explicit same-origin human finite forwarding required')
        if not self.available():
            raise Conflict('original finite owner unavailable')
        with inbox._db(write=True) as db:
            with inbox.auth.operator_guard(token, project_id=inbox.project_id, csrf=csrf) as guard:
                principal = guard.check().principal
                value, claim = inbox._decode(inbox._rows(db, rid=rid))
                if value['action'] != ACTION or digest(value) != request_hash:
                    raise RequestConflict('exact saved finite suggestion required')
                self.exact(value['stop_scope'])
                if not allowed(principal, value, human=True):
                    raise PermissionError('whole finite human operator required')
                actor = {'id': principal.id, 'kind': 'human'}
                if claim is None:
                    if resume_cleanup:
                        raise RequestConflict('no original unknown cleanup to resume')
                    key = 'forward_' + rid[8:]
                    claim = {'schema_version': '1.0', 'action': 'forward_finite_stop', 'actor': actor,
                        'idempotency_key': key, 'request_hash': digest(value), 'stop_scope': value['stop_scope'],
                        'command_id': command_id(value['stop_scope'], actor, key)}
                    decode(inbox, value, claim, rid)
                    db.execute('UPDATE requests SET claim=? WHERE id=? AND claim IS NULL', (canonical(claim).decode(), rid))
                elif claim['actor'] != actor:
                    raise RequestConflict('original forwarding human is frozen')
                inbox._pure(); self.exact(value['stop_scope'])
                if not allowed(guard.check().principal, value, human=True):
                    raise PermissionError('whole finite operator still required')
                db.commit()
        # No inbox/Auth lock across original source reads or real STOP work.
        source = self.source(claim)
        if source is not None and (not resume_cleanup or source['status'] == 'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'):
            return None  # Read-only ordinary retry: no repeated prepare/cancel.
        with self.coordinator._lock:
            pending = self.coordinator._rows.get((claim['actor']['id'], claim['idempotency_key']))
            if pending is not None and pending['running']:
                return None  # The actual original future owns cleanup lifetime.
        batch = self.coordinator.prepare({'action': STOP_ACTION}, token=token, csrf=csrf,
            origin=origin, idempotency_key=claim['idempotency_key'])
        if batch.id != claim['command_id']:
            raise Conflict('original finite batch identity differs')
        return batch

    def execute(self, batch, *, resume_cleanup):
        self.identity()
        if batch is not None:
            self.coordinator.execute_prepared(batch, _resume_unknown=resume_cleanup)
