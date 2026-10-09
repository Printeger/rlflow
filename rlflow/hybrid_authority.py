"""Immutable human consent/revocation facts, never an execution grant.

Live writes require a protected-startup bound owner and its actually issued
session guard. Historical validation deliberately needs neither live credentials
nor today's clock/catalog. No lease, task, model, or HTTP write route is started.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import secrets
import threading
from urllib.parse import urlsplit

from .hybrid_goals import (bounded_copy, check_bytes, digest, head_key, control_command_key, SECTIONS as GOALS,
                           validate_record as validate_goal_record, validate_source as validate_goal_source, draft_head)
from .hybrid_protocol import ID, HASH, COUNT, TIME, TEXT, obj, enum, nullable, validate_schema, ProtocolError
from .hybrid_registry import Registry, CATALOG
from .store import Conflict, sha
from .web_auth import AuthStore

SECTIONS = ('hybrid_approval_facts', 'hybrid_approval_revocations',
            'hybrid_approval_heads', 'hybrid_approval_commands')
EVENTS = {'approve': 'HYBRID_GOAL_APPROVED', 'revoke': 'HYBRID_APPROVAL_REVOKED'}
ACTOR = obj({'id': ID, 'kind': {'const': 'human'}})
POSITIVE = {'type': 'integer', 'minimum': 1, 'maximum': 2**63-1}
CONFIRMATION = obj({'id': ID, 'goal_id': ID, 'store_epoch': ID,
                    'expected_version': POSITIVE, 'expected_revision': POSITIVE,
                    'expected_authority_revision': COUNT, 'proposal_hash': HASH,
                    'scope_hash': HASH, 'config_hash': HASH,
                    'ttl_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 86400},
                    'view_hash': HASH})
COMMON = {'project_id': ID, 'data_mode': enum('live', 'fixture'), 'actor': ACTOR, 'idempotency_key': ID}
APPROVE_REQUEST = obj({**COMMON, 'action': {'const': 'approve'}, 'confirmation': CONFIRMATION})
REVOKE_REQUEST = obj({**COMMON, 'action': {'const': 'revoke'}, 'goal_id': ID,
                      'approval_key': ID, 'expected_version': POSITIVE,
                      'expected_authority_revision': POSITIVE, 'reason': TEXT})
for schema in (APPROVE_REQUEST,REVOKE_REQUEST):schema['properties']['control_command_id']=ID
REQUEST = {'oneOf': [APPROVE_REQUEST, REVOKE_REQUEST]}
CHAIN = {'authority_revision': POSITIVE, 'previous_fact_key': nullable(ID), 'previous_fact_hash': nullable(HASH)}
RECORDS = {
    SECTIONS[0]: obj({'request': APPROVE_REQUEST, 'approved_at': TIME, 'expires_at': TIME,
                     'registry_witness': CATALOG, **CHAIN}),
    SECTIONS[1]: obj({'request': REVOKE_REQUEST, 'revoked_at': TIME, **CHAIN}),
    SECTIONS[2]: obj({'project_id': ID, 'data_mode': enum('live', 'fixture'), 'goal_id': ID,
                     'authority_revision': POSITIVE, 'fact_section': enum(SECTIONS[0], SECTIONS[1]),
                     'fact_key': ID, 'fact_hash': HASH, 'approval_key': ID,
                     'state': enum('LEASE_VALIDATION_PENDING', 'REVOKED')}),
    SECTIONS[3]: obj({'request': REQUEST, 'request_hash': HASH, 'fact_section': enum(SECTIONS[0], SECTIONS[1]),
                     'fact_key': ID, 'fact_hash': HASH, 'accepted_state_version': POSITIVE}),
}


def command_key(request):
    if 'control_command_id' in request:return request['control_command_id']
    return 'authority_command_' + sha([request['action'], request['actor'], request['project_id'],
                                       request['data_mode'], request['idempotency_key']])


def fact_key(request):
    return ('approval_' + sha(request['confirmation']['id']) if request['action'] == 'approve'
            else 'revocation_' + sha(request))


def goal_id(request):
    return request['confirmation']['goal_id'] if request['action'] == 'approve' else request['goal_id']


def expected_version(request):
    return request['confirmation']['expected_version'] if request['action'] == 'approve' else request['expected_version']


def expected_authority_revision(request):
    return (request['confirmation']['expected_authority_revision'] if request['action'] == 'approve'
            else request['expected_authority_revision'])


def timestamp(value):
    if not value.endswith('Z'):raise ProtocolError('authority timestamp must be UTC')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def validate_request(request):
    check_bytes(request)
    validate_schema(REQUEST, request)
    if ('control_command_id' in request and request['control_command_id']!=control_command_key(
            request['actor'],request['project_id'],request['data_mode'],request['idempotency_key'])):
        raise ProtocolError('control command identity mismatch')
    counters = [expected_version(request), expected_authority_revision(request)]
    if request['action'] == 'approve':counters += [request['confirmation']['expected_revision'], request['confirmation']['ttl_seconds']]
    if any(type(n) is not int or not 0 <= n <= 2**63-1 for n in counters):
        raise ProtocolError('invalid authority integer')


def validate_record(section, key, record):
    check_bytes(record, 1024*1024)
    validate_schema(RECORDS[section], record)
    if section in SECTIONS[:2]:
        request = record['request'];validate_request(request)
        if key != fact_key(request) or record['authority_revision'] != expected_authority_revision(request)+1:
            raise ProtocolError('authority fact identity mismatch')
        if (record['authority_revision'] == 1) != (record['previous_fact_key'] is None):
            raise ProtocolError('authority predecessor mismatch')
        if (record['previous_fact_key'] is None) != (record['previous_fact_hash'] is None):
            raise ProtocolError('authority predecessor hash missing')
        if section == SECTIONS[0]:
            approved, expires = timestamp(record['approved_at']), timestamp(record['expires_at'])
            if expires-approved != timedelta(seconds=request['confirmation']['ttl_seconds']):
                raise ProtocolError('approval lifetime mismatch')
            Registry(record['registry_witness'])  # Pure historical shape/content check.
        else:timestamp(record['revoked_at'])
    elif section == SECTIONS[2]:
        if key != head_key(record['project_id'], record['data_mode'], record['goal_id']):
            raise ProtocolError('authority head identity mismatch')
        if (record['fact_section'] == SECTIONS[0]) != (record['state'] == 'LEASE_VALIDATION_PENDING'):
            raise ProtocolError('authority head state mismatch')
    else:
        request = record['request'];validate_request(request)
        if (key != command_key(request) or record['request_hash'] != digest(request)
                or record['fact_key'] != fact_key(request)
                or record['fact_section'] != SECTIONS[0 if request['action'] == 'approve' else 1]
                or record['accepted_state_version'] != expected_version(request)+1):
            raise ProtocolError('authority receipt identity mismatch')


def validate_persisted(state):
    for section in SECTIONS:
        for key, value in state.get(section, {}).items():validate_record(section, key, value)


def _approval_binding(fact, lookup):
    request = fact['request'];confirm = request['confirmation']
    hk = head_key(request['project_id'], request['data_mode'], confirm['goal_id'])
    # Revision identity is deterministic and independently checked by draft validators.
    from .hybrid_goals import revision_key
    rk = revision_key({'project_id':request['project_id'], 'data_mode':request['data_mode'],
                       'goal_id':confirm['goal_id'], 'contract_version':confirm['expected_revision']})
    record = lookup(GOALS[0], rk)
    if record is None:raise Conflict('approved draft missing')
    validate_goal_record(GOALS[0], rk, record)
    proposal = record['contract']['proposal']
    binding = Registry(fact['registry_witness']).resolve(proposal)
    profile=fact['registry_witness']['runtime_profile']
    if (proposal['budget']['model_token_enforcement']=='hard_required'
            and any(proposal['budget'][name]>0 for name in ('model_sessions','model_input_tokens','model_output_tokens'))
            and profile.get('token_limit_enforcement')=='UNSUPPORTED'):
        raise ProtocolError('hard token configuration cannot be guaranteed','UNSUPPORTED_CAPABILITY')
    if any(confirm[name] != binding[name] for name in ('proposal_hash', 'scope_hash', 'config_hash')):
        raise Conflict('approval scope witness mismatch')
    view = {'proposal': proposal, 'changes': record['changes'], 'binding': binding,
            'confirmation': {k:v for k,v in confirm.items() if k != 'view_hash'},
            'execution_status': 'LEASE_VALIDATION_PENDING','execution_enabled':False,
            'limitations':['ACTUAL_DATA_BYTES_NOT_VERIFIED','ACTUAL_OS_AND_RESOURCE_ENFORCEMENT_NOT_VERIFIED']}
    if confirm['view_hash'] != digest(view):raise Conflict('approval confirmation view mismatch')
    return hk, rk, binding


def _validate_approval(fact, lookup):
    # Preserve the original historical validation API. The preparation caller
    # can reuse the binding computed by the FULL same validation, not supply a
    # prevalidated DTO/flag or skip any original source/confirmation check.
    return _approval_binding(fact, lookup)[:2]


def _head(request, section, key, fact):
    return {'project_id': request['project_id'], 'data_mode': request['data_mode'], 'goal_id': goal_id(request),
            'authority_revision': fact['authority_revision'], 'fact_section': section, 'fact_key': key,
            'fact_hash': digest(fact), 'approval_key': key if section == SECTIONS[0] else request['approval_key'],
            'state': 'LEASE_VALIDATION_PENDING' if section == SECTIONS[0] else 'REVOKED'}


def validate_transition(payload, lookup, *, event_type, key, object_id, producer, version, registration):
    """Historical data gate; actual live authentication is separately mandatory."""
    if payload.get('format') != 2:
        if set(payload.get('set', {})) & set(SECTIONS):raise Conflict('authority requires object transactions')
        return
    if not any(s in SECTIONS for s,k,v in payload['put']) and not any(s in SECTIONS for s,k in payload['delete']):return
    puts = {(s,k):v for s,k,v in payload['put'] if k}
    markers = [(s,v) for s,k,v in payload['put'] if not k]
    if (payload['delete'] or len(puts) != 3 or len(puts)+len(markers) != len(payload['put'])
            or len({s for s,v in markers}) != len(markers) or any(s not in SECTIONS or v != {} or lookup(s,'') is not None for s,v in markers)):
        raise Conflict('invalid authority transaction shape')
    receipt_rows = [(k,v) for (s,k),v in puts.items() if s == SECTIONS[3]]
    if len(receipt_rows) != 1:raise Conflict('authority receipt required')
    ck, receipt = receipt_rows[0];validate_record(SECTIONS[3], ck, receipt)
    request = receipt['request'];fs, fk = receipt['fact_section'], receipt['fact_key']
    fact = puts.get((fs,fk));hk = head_key(request['project_id'],request['data_mode'],goal_id(request))
    head = puts.get((SECTIONS[2],hk))
    if fact is None or head is None:raise Conflict('authority fact/head required')
    validate_record(fs,fk,fact);validate_record(SECTIONS[2],hk,head)
    if (event_type != EVENTS[request['action']] or producer != 'hybrid-core' or key != ck
            or object_id != digest(request) or receipt['accepted_state_version'] != version
            or registration != (request['project_id'],request['data_mode'])
            or fact['request'] != request or receipt['fact_hash'] != digest(fact)
            or head != _head(request,fs,fk,fact)):
        raise Conflict('authority event/fact/receipt mismatch')
    if lookup(fs,fk) is not None or lookup(SECTIONS[3],ck) is not None:raise Conflict('immutable authority fact or receipt')
    old = lookup(SECTIONS[2],hk)
    if old is not None:validate_record(SECTIONS[2],hk,old)
    if (old['authority_revision'] if old else 0) != expected_authority_revision(request):raise Conflict('stale authority revision')
    if (fact['previous_fact_key'],fact['previous_fact_hash']) != ((old['fact_key'],old['fact_hash']) if old else (None,None)):
        raise Conflict('authority chain mismatch')
    if fs == SECTIONS[0]:
        _,rk = _validate_approval(fact,lookup)
        draft_head = lookup(GOALS[1],hk)
        if draft_head is None or draft_head['contract_key'] != rk or draft_head['contract_hash'] != request['confirmation']['proposal_hash']:
            raise Conflict('approval is not current draft revision')
    else:
        approval = lookup(SECTIONS[0],request['approval_key'])
        if old is None or old['state'] != 'LEASE_VALIDATION_PENDING' or old['approval_key'] != request['approval_key'] or approval is None:
            raise Conflict('revocation target is not active consent')
        if goal_id(approval['request']) != goal_id(request):raise Conflict('revocation goal mismatch')


def validate_complete(state, registration=None, event_lookup=None):
    validate_persisted(state)
    facts = {k:(s,v) for s in SECTIONS[:2] for k,v in state.get(s,{}).items()}
    if len(facts) != sum(len(state.get(s,{})) for s in SECTIONS[:2]):raise Conflict('duplicate authority fact key')
    latest = {};covered = set();revisions=set()
    fact_versions={r['fact_key']:r['accepted_state_version'] for r in state.get(SECTIONS[3],{}).values()}
    lookup = lambda s,k:state.get(s,{}).get(k)
    for fk,(fs,fact) in facts.items():
        request = fact['request'];hk = head_key(request['project_id'],request['data_mode'],goal_id(request))
        revision=(hk,fact['authority_revision'])
        if revision in revisions:raise Conflict('authority revision fork')
        revisions.add(revision)
        if registration != (request['project_id'],request['data_mode']):raise Conflict('authority registration mismatch')
        prior = facts.get(fact['previous_fact_key'])
        if fact['authority_revision'] > 1:
            if prior is None or digest(prior[1]) != fact['previous_fact_hash'] or prior[1]['authority_revision']+1 != fact['authority_revision']:
                raise Conflict('authority predecessor missing')
            if fact_versions.get(fact['previous_fact_key'],state['version']+1)>=fact_versions.get(fk,0):raise Conflict('authority source order mismatch')
            pr = prior[1]['request']
            if (pr['project_id'],pr['data_mode'],goal_id(pr)) != (request['project_id'],request['data_mode'],goal_id(request)):
                raise Conflict('authority predecessor scope mismatch')
        if fs == SECTIONS[0]:_validate_approval(fact,lookup)
        else:
            if prior is None or prior[0] != SECTIONS[0] or fact_key(prior[1]['request']) != request['approval_key']:
                raise Conflict('revocation predecessor is not approved consent')
        if hk not in latest or fact['authority_revision'] > latest[hk][1]['authority_revision']:latest[hk]=(fs,fact)
    heads = state.get(SECTIONS[2],{})
    if set(heads) != set(latest):raise Conflict('authority heads incomplete')
    for hk,(fs,fact) in latest.items():
        if heads[hk] != _head(fact['request'],fs,fact_key(fact['request']),fact):raise Conflict('authority head not latest')
    for ck, receipt in state.get(SECTIONS[3],{}).items():
        fk = receipt['fact_key'];found = facts.get(fk)
        if (found is None or found[0] != receipt['fact_section'] or found[1]['request'] != receipt['request']
                or digest(found[1]) != receipt['fact_hash'] or fk in covered
                or receipt['accepted_state_version'] > state['version'] or event_lookup is None
                or event_lookup(ck) != ((EVENTS[receipt['request']['action']], 'hybrid-core', receipt['request_hash'], receipt['accepted_state_version']),
                    sorted([(found[0],fk,digest(found[1])),(SECTIONS[3],ck,digest(receipt)),
                            (SECTIONS[2],head_key(receipt['request']['project_id'],receipt['request']['data_mode'],goal_id(receipt['request'])),
                             digest(_head(receipt['request'],found[0],fk,found[1])))]))):
            raise Conflict('authority receipt/source mismatch')
        covered.add(fk)
    if covered != set(facts):raise Conflict('authority fact lacks original receipt')


class ApprovalService:
    """Protected single-owner integration API, not callable from agent JSON."""
    def __init__(self, store, auth, registry, *, project_id, data_mode, origin, clock=None):
        parsed = urlsplit(origin)
        if (type(auth) is not AuthStore or type(registry) is not Registry or parsed.scheme not in ('http','https')
                or not parsed.netloc or parsed.username or parsed.path or parsed.query or parsed.fragment):
            raise ValueError('invalid protected approval service')
        config = json.loads(registry._raw)
        if (config['project_id'],config['data_mode']) != (project_id,data_mode):raise ValueError('approval registry scope mismatch')
        self.store,self.auth,self.registry = store,auth,registry
        self.project_id,self.data_mode,self.origin = project_id,data_mode,origin
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self._confirmations = {}
        self._confirmation_lock = threading.Lock()
        self._active_writes = {}
        store.bind_hybrid_authority(auth, registry, self)

    def check_live_write(self, request, fact, guard):
        """Writer live gate, also rejects generic authenticated fabricated facts."""
        session_key=self.auth.approval_guard_session_key(guard,project_id=self.project_id)
        with self._confirmation_lock:staged=deepcopy(self._active_writes.get(guard))
        if staged!={'request_hash':digest(request),'fact_hash':digest(fact)}:
            raise PermissionError('actual service-staged authority fact required')
        if request['action']=='revoke':return
        c=request['confirmation']
        with self._confirmation_lock:cached=deepcopy(self._confirmations.get(c['id']))
        if (cached is None or cached['confirmation']!=c or cached['session']!=session_key
                or cached['expires']<=self.auth.clock() or self.clock()>=timestamp(fact['expires_at'])):
            raise PermissionError('actual served session confirmation required')

    def _session(self, token, csrf, origin):
        if origin != self.origin:raise PermissionError('same-origin approval required')
        with self.auth.approval_guard(token,project_id=self.project_id,csrf=csrf) as guard:
            return guard.check()

    def prepare(self, *, token, csrf, origin, goal_id, ttl_seconds):
        access = self._session(token,csrf,origin)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:raise ProtocolError('invalid finite consent lifetime')
        validate_schema(ID,goal_id)
        hk = head_key(self.project_id,self.data_mode,goal_id)
        with self.store.connect() as db:
            db.execute('BEGIN')
            meta = db.execute('SELECT project_id,data_mode,store_epoch FROM observation_meta WHERE singleton=1').fetchone()
            if meta is None or tuple(meta[:2]) != (self.project_id,self.data_mode):raise Conflict('approval project registration mismatch')
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db)
            read=budget.object
            try:
                head=read(GOALS[1],hk)
                if head is None:raise Conflict('draft not found')
                validate_goal_record(GOALS[1],hk,head)
                record=read(GOALS[0],head['contract_key']);validate_goal_record(GOALS[0],head['contract_key'],record)
                if head!=draft_head(record['contract']['proposal']):raise Conflict('draft current head mismatch')
                if 'source_command_key' in record:
                    ck=record['source_command_key'];receipt=read(GOALS[2],ck)
                    if receipt is None:raise Conflict('draft original receipt missing')
                    validate_goal_source(head['contract_key'],record,ck,receipt,self.store._goal_source(
                        db,ck,max_bytes=budget.remaining,_parse=budget.parse,_decode=budget.decode))
            except ProtocolError:
                raise Conflict('draft source invalid') from None
            authority=read(SECTIONS[2],hk)
            binding=self.registry.resolve(record['contract']['proposal'])
            confirm={'id':'confirmation_'+secrets.token_hex(32),'goal_id':goal_id,'store_epoch':meta['store_epoch'],
                     'expected_version':db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0],
                     'expected_revision':head['revision'],'expected_authority_revision':authority['authority_revision'] if authority else 0,
                     'proposal_hash':binding['proposal_hash'],'scope_hash':binding['scope_hash'],
                     'config_hash':binding['config_hash'],'ttl_seconds':ttl_seconds}
            view={'proposal':record['contract']['proposal'],'changes':record['changes'],'binding':binding,
                  'confirmation':deepcopy(confirm),'execution_status':'LEASE_VALIDATION_PENDING','execution_enabled':False,
                  'limitations':['ACTUAL_DATA_BYTES_NOT_VERIFIED','ACTUAL_OS_AND_RESOURCE_ENFORCEMENT_NOT_VERIFIED']}
            confirm['view_hash']=digest(view)
        now=self.auth.clock()
        with self._confirmation_lock:
            self._confirmations={k:v for k,v in self._confirmations.items() if v['expires']>now}
            if len(self._confirmations)>=128:raise ProtocolError('confirmation capacity reached')
            self._confirmations[confirm['id']]={'confirmation':deepcopy(confirm),'session':self.auth._key(token),
                                               'expires':min(now+120,access.expires_at)}
        return {**view,'confirmation':confirm}

    def approve(self, confirmation, *, token, csrf, origin, idempotency_key, _control_command_id=None):
        access=self._session(token,csrf,origin);confirm=bounded_copy(confirmation);validate_schema(CONFIRMATION,confirm)
        request={'action':'approve','project_id':self.project_id,'data_mode':self.data_mode,
                 'actor':{'id':access.principal.id,'kind':'human'},'idempotency_key':idempotency_key,'confirmation':confirm}
        if _control_command_id is not None:request['control_command_id']=_control_command_id
        return self._write(request,token,csrf)

    def revoke(self, *, token, csrf, origin, goal_id, approval_key, expected_version,
               expected_authority_revision, reason, idempotency_key, _control_command_id=None):
        access=self._session(token,csrf,origin)
        request={'action':'revoke','project_id':self.project_id,'data_mode':self.data_mode,
                 'actor':{'id':access.principal.id,'kind':'human'},'idempotency_key':idempotency_key,
                 'goal_id':goal_id,'approval_key':approval_key,'expected_version':expected_version,
                 'expected_authority_revision':expected_authority_revision,'reason':reason}
        if _control_command_id is not None:request['control_command_id']=_control_command_id
        return self._write(request,token,csrf)

    def _write(self, request, token, csrf):
        request=bounded_copy(request);validate_request(request)
        ck,fk=command_key(request),fact_key(request);fs=SECTIONS[0 if request['action']=='approve' else 1]
        hk=head_key(self.project_id,self.data_mode,goal_id(request))
        selected=[(SECTIONS[2],hk),(SECTIONS[3],ck),(fs,fk)]
        staged_expiry=[None]
        issued_guard=[None]
        def final_check():
            if staged_expiry[0] is None:return  # Historical duplicate, not fresh consent.
            c=request['confirmation']
            with self._confirmation_lock:cached=deepcopy(self._confirmations.get(c['id']))
            if cached is None or cached['expires']<=self.auth.clock() or self.clock()>=staged_expiry[0]:
                raise PermissionError('confirmation or consent expired before commit')
        @contextmanager
        def authorization():
            with self.auth.approval_guard(token,project_id=self.project_id,csrf=csrf,_validator=final_check) as guard:
                issued_guard[0]=guard
                with self._confirmation_lock:self._active_writes[guard]={'request_hash':digest(request),'fact_hash':None}
                try:yield guard
                finally:
                    with self._confirmation_lock:self._active_writes.pop(guard,None)
        def mutate(state):
            old=state.get(SECTIONS[2],{}).get(hk)
            now=self.clock()
            if now.tzinfo != timezone.utc:raise ProtocolError('approval clock must be UTC')
            if request['action']=='approve':
                c=request['confirmation']
                with self._confirmation_lock:cached=deepcopy(self._confirmations.get(c['id']))
                if (cached is None or cached['confirmation']!=c or cached['session']!=self.auth._key(token)
                        or cached['expires']<=self.auth.clock()):raise PermissionError('fresh session-bound confirmation required')
                fact={'request':request,'approved_at':now.isoformat().replace('+00:00','Z'),
                      'expires_at':(now+timedelta(seconds=c['ttl_seconds'])).isoformat().replace('+00:00','Z'),
                      'registry_witness':json.loads(self.registry._raw)}
                staged_expiry[0]=timestamp(fact['expires_at'])
            else:fact={'request':request,'revoked_at':now.isoformat().replace('+00:00','Z')}
            fact.update(authority_revision=expected_authority_revision(request)+1,
                        previous_fact_key=old['fact_key'] if old else None,previous_fact_hash=old['fact_hash'] if old else None)
            with self._confirmation_lock:self._active_writes[issued_guard[0]]['fact_hash']=digest(fact)
            state.setdefault(fs,{})[fk]=fact
            state.setdefault(SECTIONS[2],{})[hk]=_head(request,fs,fk,fact)
            state.setdefault(SECTIONS[3],{})[ck]={'request':request,'request_hash':digest(request),'fact_section':fs,
                'fact_key':fk,'fact_hash':digest(fact),'accepted_state_version':state['version']+1}
        result=self.store.transact_objects(EVENTS[request['action']],ck,selected,mutate,expected=expected_version(request),
            object_id=digest(request),producer='hybrid-core',
            _authorization=authorization)
        with self.store.connect() as db:
            db.execute('BEGIN')
            def read(s,k):
                row=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(s,k)).fetchone()
                return self.store._decode_value(db,json.loads(row[0])) if row else None
            receipt,fact=read(SECTIONS[3],ck),read(fs,fk)
            if receipt is None or fact is None:raise Conflict('authority fact or original receipt missing')
            validate_record(SECTIONS[3],ck,receipt);validate_record(fs,fk,fact)
            if (receipt['request']!=request or receipt['fact_hash']!=digest(fact)
                    or self.store._goal_registration(db)!=(self.project_id,self.data_mode)
                    or self.store._authority_event(db,ck)!=((EVENTS[request['action']],'hybrid-core',digest(request),receipt['accepted_state_version']),
                        sorted([(fs,fk,digest(fact)),(SECTIONS[3],ck,digest(receipt)),(SECTIONS[2],hk,digest(_head(request,fs,fk,fact)))]))):
                raise Conflict('authority retry original source mismatch')
        if request['action']=='approve':
            with self._confirmation_lock:self._confirmations.pop(request['confirmation']['id'],None)
        return {'fact_key':fk,'fact':fact,'accepted_state_version':receipt['accepted_state_version'],
                'duplicate':result['duplicate'],'execution_enabled':False,
                'execution_status':'LEASE_VALIDATION_PENDING' if fs==SECTIONS[0] else 'REVOKED'}
