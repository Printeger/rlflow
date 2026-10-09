"""Actual-owner, durable Hybrid core-fact fencing, never a worker lease.

This service does not fence legacy dispatch or workspace writers. All execution
and candidate-write flags remain false; expired takeover does not prove cleanup.
Tokens are process-local actual issued objects, never reconstructed from facts.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
import uuid
import weakref

from .hybrid_controller import (SECTIONS, EVENT, REQUEST, fact_key, scope_key, head,
    validate_record, validate_current_point)
from .hybrid_goals import digest
from .hybrid_protocol import validate_schema
from .hybrid_reads import ReadBudget
from .hybrid_registry import Registry
from .hybrid_authority import timestamp
from .jobs import identity
from .policy import stopped
from .store import Store, Conflict, canonical

READ_BYTES=4*1024**2


@dataclass(frozen=True, eq=False)
class ControllerToken:
    """Only object identity in the fixed service cache confers core-fact use."""
    key: str
    raw: bytes


class _Guard:
    def __init__(self,owner,record,previous):
        self.owner=owner;self.raw=canonical(record);self.budget=None
        self.previous=None if previous is None else canonical(previous)

    def check(self):
        self.owner._check_active(self)


class ControllerService:
    def __init__(self,store,registry,*,project_id,data_mode,store_epoch,
                 clock=lambda:datetime.now(timezone.utc),monotonic_ns=time.monotonic_ns):
        if type(store) is not Store or type(registry) is not Registry:
            raise TypeError('fixed actual controller components required')
        config=json.loads(registry._raw)
        if (config['project_id'],config['data_mode'])!=(project_id,data_mode):
            raise Conflict('controller owner scope differs')
        process=identity(os.getpid())
        if process is None:raise Conflict('actual controller process unavailable')
        self.store,self.registry=store,registry
        self.project_id,self.data_mode,self.store_epoch=project_id,data_mode,store_epoch
        self.owner={'id':'controller_'+uuid.uuid4().hex,'process':process}
        self._owner_raw=canonical(self.owner);self._config_hash=registry.config_hash
        self.clock,self.monotonic_ns=clock,monotonic_ns
        # Do not retain discarded obsolete revisions forever. Callers must hold
        # their actual token; losing it never authorizes reconstruction from disk.
        self._last_sample=None;self._active=None;self._tokens=weakref.WeakValueDictionary();self._lock=threading.RLock()
        self._token_active=None
        store.bind_hybrid_controller(self)

    def _sample(self):
        now=self.clock();mono=self.monotonic_ns()
        if (type(now) is not datetime or now.tzinfo is None or now.utcoffset().total_seconds()!=0 or
                type(mono) is not int or not 0<=mono<=2**63-1):
            raise Conflict('controller requires actual UTC and monotonic clock')
        if self._last_sample is not None and (now<self._last_sample[0] or mono<self._last_sample[1]):
            raise Conflict('controller clock regressed')
        self._last_sample=(now,mono)
        return now,mono

    def _owner_live(self):
        if (canonical(self.owner)!=self._owner_raw or identity(os.getpid())!=self.owner['process'] or
                self.registry.config_hash!=self._config_hash):
            raise Conflict('controller actual process or registry changed')
        if stopped(self.store.root):raise Conflict('controller STOP is present')

    def _metadata(self,db):
        row=db.execute('SELECT project_id,data_mode,store_epoch,source_version FROM observation_meta WHERE singleton=1').fetchone()
        version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
        if (row is None or tuple(row[:3])!=(self.project_id,self.data_mode,self.store_epoch) or
                type(version) is not int or not 0<=version<=2**63-1 or version!=row['source_version'] or
                version!=db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]):
            raise Conflict('controller registration, epoch or source version changed')
        return version

    def _original(self,db,key,budget):
        value=budget.object(SECTIONS[0],key)
        if value is None:raise Conflict('controller original fact missing')
        validate_record(SECTIONS[0],key,value)
        hk=scope_key(self.project_id,self.data_mode)
        proof=self.store._controller_event(db,key,max_bytes=min(budget.remaining,256*1024),
                                          _parse=budget.parse,_decode=budget.decode)
        if proof!=((EVENT,'hybrid-core',digest(value),value['accepted_state_version']),
                   sorted([(SECTIONS[0],key,digest(value)),(SECTIONS[1],hk,digest(head(value)))])):
            raise Conflict('controller original fact/head event differs')
        return value

    def _current(self,db,budget):
        hk=scope_key(self.project_id,self.data_mode);current=budget.object(SECTIONS[1],hk)
        tip=db.execute('SELECT idempotency_key,new_state_version FROM events WHERE event_type=? ORDER BY seq DESC LIMIT 1',(EVENT,)).fetchone()
        if current is None:
            if tip is not None or any(db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(s,)).fetchone() for s in SECTIONS):
                raise Conflict('controller head missing from existing domain')
            return None
        validate_record(SECTIONS[1],hk,current)
        if tip is None or tip['idempotency_key']!=current['fact_key']:
            raise Conflict('controller current head differs from original event tip')
        value=self._original(db,current['fact_key'],budget)
        pk=value['request']['previous_fact_key']
        previous=None if pk is None else self._original(db,pk,budget)
        validate_current_point(current,value,previous,registration=(self.project_id,self.data_mode),
                               version=self._metadata(db),event_tip=tuple(tip))
        return value

    def _issued(self,token):
        if type(token) is not ControllerToken or self._tokens.get(token.key) is not token:
            raise PermissionError('actual issued controller token required')
        return json.loads(token.raw)

    def _token_live(self,db,token,budget):
        value=self._issued(token);self._owner_live();now,mono=self._sample()
        current=self._current(db,budget)
        if (current!=value or value['request']['owner']!=self.owner or
                value['request']['store_epoch']!=self.store_epoch or
                not timestamp(value['issued_at'])<=now<timestamp(value['expires_at']) or
                not value['issued_monotonic_ns']<=mono<value['expires_monotonic_ns']):
            raise Conflict('controller token expired or current fence changed')
        return value

    def check_token(self,token):
        """Read-only live core-fact check; explicitly not execution admission."""
        with self._lock,self.store.read_connection() as db:
            db.execute('BEGIN');self._metadata(db)
            value=self._token_live(db,token,ReadBudget(db,READ_BYTES))
            return {'controller_epoch':value['controller_epoch'],'head_revision':value['head_revision'],
                    'authority_domain':'HYBRID_CORE_FACTS_ONLY','execution_enabled':False}

    @contextmanager
    def token_transaction(self,token,*,read_bytes=READ_BYTES,_before_commit=None,_after_final_sample=None,_on_exit=None):
        """Mint a fresh fixed-Store writer, hold owner lock, recheck and commit.

        Never accepts a caller's connection/read snapshot. Internal owner API;
        do not expose DB/budget/token as JSON or manually commit inside context.
        """
        self._refuse_nested_writer();self._issued(token)
        if type(read_bytes) is not int or not 1<=read_bytes<=64*1024**2:
            raise Conflict('invalid controller transaction read envelope')
        if _before_commit is not None and not callable(_before_commit):
            raise TypeError('internal final-check callback required')
        if _after_final_sample is not None and not callable(_after_final_sample):
            raise TypeError('internal pure deadline callback required')
        if _on_exit is not None and not callable(_on_exit):
            raise TypeError('internal held-writer cleanup callback required')
        with self.store.lock(),self._lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');budget=ReadBudget(db,read_bytes)
            if self.store._hybrid_controller_service is not self:
                raise PermissionError('actual bound controller owner required')
            if self._token_active is not None:raise Conflict('nested controller token transaction refused')
            self._token_active=(db,token,budget,threading.get_ident())
            try:
                self._metadata(db);value=self._token_live(db,token,budget)
                yield db,budget,value
                self.check_token_in_transaction(db,token,budget)
                if _before_commit is not None:_before_commit()
                # Source/head proof callbacks can be expensive. Sample actual
                # owner, STOP and both deadlines AFTER all such reads, with no
                # subsequent source expansion before the owned COMMIT.
                now,mono=self._final_token_freshness(db,token,budget)
                # Internal owner deadline comparisons ONLY: no SQL, source
                # expansion, file IO or new authority after this final sample.
                if _after_final_sample is not None:_after_final_sample(now,mono)
                db.commit()
            finally:
                self._token_active=None
                # Release service active context BEFORE writer/owner unlock,
                # including rollback/uncertain-return paths. Internal cleanup
                # only: this hook never supplies execution authority.
                if _on_exit is not None:_on_exit()

    def _final_token_freshness(self,db,token,budget):
        active=self._token_active
        if (active is None or active[0] is not db or active[1] is not token or active[2] is not budget or
                active[3]!=threading.get_ident() or not db.in_transaction or
                self.store._hybrid_controller_service is not self):
            raise PermissionError('actual final held controller transaction required')
        value=self._issued(token);self._owner_live();now,mono=self._sample()
        if (value['request']['owner']!=self.owner or value['request']['store_epoch']!=self.store_epoch or
                not timestamp(value['issued_at'])<=now<timestamp(value['expires_at']) or
                not value['issued_monotonic_ns']<=mono<value['expires_monotonic_ns']):
            raise Conflict('controller token expired at final owned commit')
        return now,mono

    def _refuse_nested_writer(self):
        if self._token_active is not None and self._token_active[3]==threading.get_ident():
            raise Conflict('nested controller authoritative writer refused')
        if self._active is not None and getattr(self._active,'thread',None)==threading.get_ident():
            raise Conflict('nested controller authoritative writer refused')

    def check_token_in_transaction(self,db,token,budget):
        """Check within token_transaction while the actual owner lock is held."""
        active=self._token_active
        if (active is None or active[0] is not db or active[1] is not token or active[2] is not budget or
                active[3]!=threading.get_ident() or not db.in_transaction or
                type(budget) is not ReadBudget or budget.db is not db):
            raise PermissionError('actual held controller transaction required')
        if self.store._hybrid_controller_service is not self:
            raise PermissionError('actual bound controller owner required')
        self._metadata(db)
        return self._token_live(db,token,budget)

    def _check_active(self,guard):
        if type(guard) is not _Guard or guard.owner is not self or self._active is not guard:
            raise PermissionError('actual active controller owner guard required')
        self._owner_live();now,mono=self._sample();value=json.loads(guard.raw)
        if (value['request']['owner']!=self.owner or value['config_hash']!=self._config_hash or
                not timestamp(value['issued_at'])<=now<timestamp(value['expires_at']) or
                not value['issued_monotonic_ns']<=mono<value['expires_monotonic_ns']):
            raise Conflict('controller issued lifetime changed or expired')
        if value['request']['operation']=='renew' and guard.previous is not None:
            previous=json.loads(guard.previous)
            if now>=timestamp(previous['expires_at']) or mono>=previous['expires_monotonic_ns']:
                raise Conflict('controller predecessor expired before renewal commit')

    def check_guard(self,db,guard):
        self._check_active(guard);self._metadata(db)
        if self.store._hybrid_controller_service is not self or not db.in_transaction:
            raise PermissionError('actual bound controller writer required')
        if guard.budget is None:guard.budget=ReadBudget(db,READ_BYTES)
        if guard.budget.db is not db:raise PermissionError('actual controller transaction required')

    def check_live_write(self,db,payload,guard):
        self.check_guard(db,guard);value=json.loads(guard.raw)
        hk=scope_key(self.project_id,self.data_mode);fk=fact_key(value['request'])
        if sorted((s,k,canonical(v)) for s,k,v in payload['put'] if k)!=sorted([
                (SECTIONS[0],fk,canonical(value)),(SECTIONS[1],hk,canonical(head(value)))]):
            raise Conflict('controller mutation differs from issued context')
        previous=self._current(db,guard.budget);request=value['request']
        if (request['expected_state_version']!=self._metadata(db) or
                request['previous_fact_key']!=(None if previous is None else fact_key(previous['request'])) or
                request['previous_fact_hash']!=(None if previous is None else digest(previous))):
            raise Conflict('controller source changed inside writer')
        if previous is not None:
            now,mono=self._sample()
            if request['operation']=='renew':
                if (now>=timestamp(previous['expires_at']) or mono>=previous['expires_monotonic_ns'] or
                        previous['request']['owner']!=self.owner):
                    raise Conflict('controller predecessor expired during renewal')
            elif request['store_epoch']==previous['request']['store_epoch']:
                if now<timestamp(previous['expires_at']) or mono<previous['expires_monotonic_ns']:
                    raise Conflict('controller predecessor remains live')
        guard.check()

    @contextmanager
    def _authorization(self,value,previous):
        if self._active is not None:raise Conflict('nested controller transaction refused')
        guard=_Guard(self,value,previous);guard.thread=threading.get_ident();self._active=guard
        try:guard.check();yield guard
        finally:self._active=None

    def acquire(self,idempotency_key,*,expected_version,ttl_seconds=30):
        return self._write('acquire',idempotency_key,expected_version,ttl_seconds,None)

    def renew(self,token,idempotency_key,*,expected_version,ttl_seconds=30):
        self._issued(token)
        return self._write('renew',idempotency_key,expected_version,ttl_seconds,token)

    def _write(self,operation,idem,expected,ttl,token):
        # Shared authority lock order: writer -> controller owner. Admission
        # holds this same order through final token check and DB commit.
        self._refuse_nested_writer()
        with self.store.lock(),self._lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');version=self._metadata(db);self._owner_live()
            budget=ReadBudget(db,READ_BYTES);previous=self._current(db,budget)
            request={'authority_domain':'HYBRID_CORE_FACTS_ONLY','project_id':self.project_id,
                'data_mode':self.data_mode,'store_epoch':self.store_epoch,'owner':json.loads(self._owner_raw),
                'operation':operation,'idempotency_key':idem,'ttl_seconds':ttl,'expected_state_version':expected,
                'expected_head_revision':0 if previous is None else previous['head_revision'],
                'previous_fact_key':None if previous is None else fact_key(previous['request']),
                'previous_fact_hash':None if previous is None else digest(previous)}
            validate_schema(REQUEST,request);key=fact_key(request)
            if db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],key)).fetchone():
                original=self._original(db,key,budget)
                if any(original['request'][n]!=request[n] for n in ('operation','ttl_seconds','expected_state_version','owner')):
                    raise Conflict('controller idempotency key reused')
                db.commit()
                return {'fact':original,'token':None,'duplicate':True,'execution_enabled':False}
            if type(expected) is not int or type(ttl) is not int or version!=expected:
                raise Conflict('controller stale version or actual integers required')
            if len(self._tokens)>=128:raise Conflict('controller issued token capacity reached')
            if operation=='renew':self._token_live(db,token,budget)
            now,mono=self._sample()
            value={'request':request,'request_hash':digest(request),'config_hash':self._config_hash,
                'controller_epoch':1 if previous is None else previous['controller_epoch']+(operation=='acquire'),
                'head_revision':request['expected_head_revision']+1,'issued_at':now.isoformat().replace('+00:00','Z'),
                'expires_at':(now+timedelta(seconds=ttl)).isoformat().replace('+00:00','Z'),
                'issued_monotonic_ns':mono,'expires_monotonic_ns':mono+ttl*10**9,
                'accepted_state_version':version+1,'reason':'INITIAL' if previous is None else (
                    'RENEWED' if operation=='renew' else ('NEW_STORE_EPOCH' if self.store_epoch!=previous['request']['store_epoch'] else 'EXPIRED_PREDECESSOR')),
                'prior_runtime_recovery':'UNVERIFIED','candidate_write_enabled':False,'execution_enabled':False}
            validate_record(SECTIONS[0],key,value);hk=scope_key(self.project_id,self.data_mode)
            payload={'format':2,'put':[[SECTIONS[0],key,value],[SECTIONS[1],hk,head(value)]],'delete':[],'details':None}
            for section in SECTIONS:
                if not db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone():
                    payload['put'].append([section,'',{}])
            with self._authorization(value,previous) as guard:
                self.store._commit(db,EVENT,key,payload,version,digest(value),'hybrid-core',{},_authorization=guard)
                guard.check();db.commit()
            issued=ControllerToken(key,canonical(value));self._tokens[key]=issued
            return {'fact':value,'token':issued,'duplicate':False,'execution_enabled':False}
