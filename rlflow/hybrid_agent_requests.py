"""Bounded non-authoritative suggestions, forwarded by original human services.

The inbox is deliberately outside the Core event/projection database. Its rows
are not Goals, approvals, leases or proof of acceptance. Only an original Core
event's complete source witness can establish an ADOPTED report. No scheduler,
model, execution, STOP latch or human approval is called by agent submission.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat as file_stat
import threading

from .hybrid_control import ControlError, command_dto
from .hybrid_drafts import DraftService
from .hybrid_goals import (bounded_copy, control_command_key, digest, SECTIONS,
                           validate_request, validate_source)
from .hybrid_protocol import ID, COUNT, HASH, obj, validate_schema, ProtocolError
from .hybrid_reads import HybridReader, ReadBudget
from .store import Conflict, canonical

MAX_ROWS = 32
MAX_BYTES = 256 * 1024


class RequestConflict(Conflict):
    """Known caller key/body/frozen-version conflict, distinct from bad sources."""


class AgentRequestService:
    """Trusted startup injection; IDs cannot reconstruct an original service."""

    def __init__(self, drafts, *, finite_stop=None):
        if type(drafts) is not DraftService or drafts.store._hybrid_draft_service is not drafts:
            raise TypeError('original protected DraftService required')
        self.drafts = drafts
        self.store, self.auth = drafts.store, drafts.auth
        self.project_id, self.data_mode, self.store_epoch = drafts.project_id, drafts.data_mode, drafts.store_epoch
        self.origin = drafts.origin
        self.stop_requests = None
        if finite_stop is not None:
            from .hybrid_agent_stop_requests import FiniteStopRequests
            self.stop_requests = FiniteStopRequests(self, finite_stop)
        self._stop_requests = self.stop_requests
        self._binding = (drafts, self.store, self.auth, self.project_id, self.data_mode, self.store_epoch, self.origin)
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self.path = self.store.root / 'agent-requests.sqlite3'
        self._path = self.path
        with self.store.lock():
            if getattr(self.store, '_hybrid_agent_request_service', None) is not None:
                raise Conflict('one original agent request service required')
            try:
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
                fresh = True
            except FileExistsError:
                fd = os.open(self.path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                fresh = False
            try:
                stat = os.fstat(fd)
                if not file_stat.S_ISREG(stat.st_mode) or stat.st_uid != os.getuid() or stat.st_nlink != 1 or stat.st_mode & 0o077:
                    raise PermissionError('private original inbox file required')
                self._file = (stat.st_dev, stat.st_ino)
            finally:
                os.close(fd)
            with sqlite3.connect(self.path) as db:
                if fresh:
                    db.execute('PRAGMA page_size=4096')
                    db.execute('CREATE TABLE requests (id TEXT PRIMARY KEY, body TEXT NOT NULL, claim TEXT)')
                    db.execute('CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), project TEXT NOT NULL, mode TEXT NOT NULL, epoch TEXT NOT NULL)')
                    db.execute('INSERT INTO metadata VALUES(1,?,?,?)', (self.project_id, self.data_mode, self.store_epoch))
                    db.commit()
                self._validate_db(db)
                db.execute('PRAGMA max_page_count=4096')  # finite 16MiB at default 4KiB pages
            self.store._hybrid_agent_request_service = self
        self._pure()

    def _validate_db(self, db):
        if db.execute('PRAGMA page_size').fetchone()[0] != 4096 or db.execute('PRAGMA page_count').fetchone()[0] > 4096:
            raise Conflict('bounded 4KiB-page original inbox required')
        # Column summaries alone miss COLLATE/UNIQUE/ON CONFLICT REPLACE,
        # which could silently delete a previous request's frozen claim.
        expected_schema = {
            ('table','requests','requests','CREATE TABLE requests (id TEXT PRIMARY KEY, body TEXT NOT NULL, claim TEXT)'),
            ('table','metadata','metadata','CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), project TEXT NOT NULL, mode TEXT NOT NULL, epoch TEXT NOT NULL)'),
            ('index','sqlite_autoindex_requests_1','requests',None),
        }
        schema = db.execute('SELECT type, CASE WHEN length(name)<=128 THEN name END, CASE WHEN length(tbl_name)<=128 THEN tbl_name END, CASE WHEN length(CAST(sql AS BLOB))<=4096 THEN sql END FROM sqlite_master ORDER BY name LIMIT 4').fetchall()
        if len(schema) != 3 or {tuple(row) for row in schema} != expected_schema:
            raise Conflict('exact original inbox DDL/index closure required')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != {'requests', 'metadata'} or db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
            raise Conflict('closed existing inbox schema required; no implicit repair')
        expected = {'requests': [('id','TEXT',0,1),('body','TEXT',1,0),('claim','TEXT',0,0)],
                    'metadata': [('singleton','INTEGER',0,1),('project','TEXT',1,0),('mode','TEXT',1,0),('epoch','TEXT',1,0)]}
        for table, columns in expected.items():
            actual = [(row[1], row[2], row[3], row[5]) for row in db.execute('PRAGMA table_info(' + table + ')')]
            if actual != columns:
                raise Conflict('closed existing inbox columns required')
        rows = db.execute('SELECT singleton, CASE WHEN length(project)<=160 THEN project END, CASE WHEN length(mode)<=7 THEN mode END, CASE WHEN length(epoch)<=64 THEN epoch END FROM metadata LIMIT 2').fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (1, self.project_id, self.data_mode, self.store_epoch):
            raise Conflict('original inbox project/mode/epoch metadata required')

    def _identity(self):
        # Check parent identity before inherited locks or sqlite after fork.
        if (os.getpid() != self._pid or getattr(self.store, '_hybrid_agent_request_service', None) is not self
                or self.stop_requests is not self._stop_requests
                or self._binding != (self.drafts, self.store, self.auth, self.project_id, self.data_mode, self.store_epoch, self.origin)
                or self.path != self._path
                or (self.drafts.store, self.drafts.auth, self.drafts.project_id, self.drafts.data_mode,
                    self.drafts.store_epoch, self.drafts.origin) != self._binding[1:]
                or self.store._hybrid_draft_service is not self.drafts
                or self.store._hybrid_draft_auth_owner is not self.auth):
            raise PermissionError('original request service binding required')
        if self.stop_requests is not None:
            self.stop_requests.identity()

    def _pure(self):
        self._identity()
        stat = self.path.lstat()
        if (stat.st_dev, stat.st_ino) != self._file or stat.st_nlink != 1 or stat.st_mode & 0o077:
            raise PermissionError('original private inbox file changed')
        with self.store.read_connection() as db:
            row = db.execute('SELECT project_id,data_mode,store_epoch FROM observation_meta WHERE singleton=1').fetchone()
        if row is None or tuple(row) != (self.project_id, self.data_mode, self.store_epoch):
            raise Conflict('request service registration/epoch changed')

    @contextmanager
    def _db(self, *, write=False):
        self._pure()
        with self._lock:
            self._pure()
            db = sqlite3.connect(self.path, timeout=2)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA max_page_count=4096')
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                self._validate_db(db)
                self._pure()
                yield db
                self._pure()
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def _request(self, proposal, *, actor, key, expected_revision):
        # Reuse the original closed contract validator without granting its
        # operator authority. This object is only a suggestion in the inbox.
        value = bounded_copy({'action': 'propose_goal_draft', 'project_id': self.project_id,
            'data_mode': self.data_mode, 'actor': actor, 'idempotency_key': key,
            'expected_revision': expected_revision, 'proposal': proposal})
        validate_request(value)
        if value['proposal']['schema_version'] != '1.1':
            raise ProtocolError('explicit 1.1 proposal required')
        return value

    @staticmethod
    def _rows(db, *, rid=None):
        # SQL bounds before fetching text, never fetch oversized raw rows.
        columns = 'id, CASE WHEN length(CAST(body AS BLOB))<=? THEN body END AS body, CASE WHEN length(CAST(claim AS BLOB))<=? THEN claim END AS claim, claim IS NOT NULL AS has_claim'
        if rid is not None:
            return db.execute('SELECT ' + columns + ' FROM requests WHERE id=?', (MAX_BYTES, MAX_BYTES, rid)).fetchone()
        return db.execute('SELECT ' + columns + ' FROM requests ORDER BY id LIMIT ?', (MAX_BYTES, MAX_BYTES, MAX_ROWS + 1)).fetchall()

    def _decode(self, row, budget=None):
        try:
            return self._decode_value(row, budget)
        except (ProtocolError, ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise Conflict('persistent inbox source invalid') from None

    def _decode_value(self, row, budget=None):
        if row is None:
            raise ControlError(404, 'NOT_FOUND', 'request not found')
        if row['body'] is None or row['has_claim'] and row['claim'] is None:
            raise Conflict('inbox row exceeds bounds')
        budget = budget or ReadBudget(None, 4 * MAX_BYTES)
        value = budget.parse(row['body'].encode())
        budget.charge_literal(value)  # Inbox marker-like dicts are data, NOT blobs.
        if type(value) is dict and value.get('action') == 'request_finite_stop':
            from .hybrid_agent_stop_requests import decode
            claim = budget.parse(row['claim'].encode()) if row['claim'] is not None else None
            if claim is not None: budget.charge_literal(claim)
            return decode(self, value, claim, row['id'])
        validate_request(value)
        if value != self._request(value['proposal'], actor=value['actor'], key=value['idempotency_key'], expected_revision=value['expected_revision']):
            raise Conflict('invalid inbox request')
        if value['actor']['kind'] != 'agent' or row['id'] != self._id(value):
            raise Conflict('inbox request identity mismatch')
        claim = budget.parse(row['claim'].encode()) if row['claim'] is not None else None
        if claim is not None:
            budget.charge_literal(claim)
            validate_request(claim)
            if (claim['actor']['kind'] != 'human' or claim.get('control_command_id') != control_command_key(
                    claim['actor'], self.project_id, self.data_mode, 'forward_' + row['id'][8:])
                    or claim['idempotency_key'] != 'forward_' + row['id'][8:]
                    or 'expected_state_version' not in claim
                    or claim['proposal'] != value['proposal']
                    or claim['expected_revision'] != value['expected_revision']):
                raise Conflict('frozen forwarding claim differs from request')
        return value, claim

    def _id(self, value):
        # Same token principal/key namespace across retries, scoped to epoch.
        return 'request_' + digest([self.project_id, self.data_mode, self.store_epoch,
            value['actor'], value['idempotency_key']]).removeprefix('sha256:')

    def submit(self, proposal, *, token, idempotency_key, expected_revision):
        self._identity()
        with self._db(write=True) as db:
            with self.auth.request_guard(token, project_id=self.project_id) as check:
                principal = check().principal
                value = self._request(proposal, actor={'id': principal.id, 'kind': 'agent'}, key=idempotency_key, expected_revision=expected_revision)
                rid = self._id(value)
                row = self._rows(db, rid=rid)
                if row is not None:
                    old, _ = self._decode(row)
                    if old != value:
                        raise RequestConflict('request idempotency key reused with different body')
                else:
                    if db.execute('SELECT count(*) FROM requests').fetchone()[0] >= MAX_ROWS:
                        raise Conflict('bounded request inbox full')
                    db.execute('INSERT INTO requests(id,body) VALUES(?,?)', (rid, canonical(value).decode()))
                # Commit while the actual token guard still blocks revoke.
                self._pure()
                check()
                db.commit()
        return self.get(rid, token=token, method='request')

    def _authorize(self, token, method, *, operator=False):
        self._identity()
        access = self.auth.resolve(token, method)
        if (access is None or method not in ('request', 'session')
                or not access.principal.allows(self.project_id)
                or (method == 'request' and access.principal.kind != 'agent')
                or (method == 'session' and (access.principal.kind != 'human'
                    or not access.principal.allows(self.project_id, 'operator')))):
            raise PermissionError('live scoped inbox access required')
        return access

    def _source(self, claim):
        """Consistent, bounded original DRAFT payload witness; no latest-head test."""
        reader = HybridReader(self.store, project_id=self.project_id, data_mode=self.data_mode, store_epoch=self.store_epoch)
        with reader.snapshot() as (db, meta):
            budget = ReadBudget(db, 4 * 1024 * 1024)
            command_id = claim['control_command_id']
            receipt = budget.object(SECTIONS[2], command_id)
            if receipt is None:
                if self.store._goal_event(db, command_id) is not None:
                    raise Conflict('original command event missing its receipt')
                version = meta['as_of_state_version']
                return None, 'STALE' if version > claim['expected_state_version'] else 'UNKNOWN'
            if receipt['request'] != claim:
                raise Conflict('original command differs from frozen forwarding body')
            record = budget.object(SECTIONS[0], receipt['contract_key'])
            if record is None:
                raise Conflict('original draft contract missing')
            validate_source(receipt['contract_key'], record, command_id, receipt,
                self.store._goal_source(db, command_id, max_bytes=budget.remaining, _parse=budget.parse, _decode=budget.decode))
            if receipt['accepted_state_version'] > meta['as_of_state_version']:
                raise Conflict('original draft source from future')
            return command_dto(command_id, receipt), 'ADOPTED'

    def _dto(self, rid, value, claim, *, private=False):
        if value['action'] == 'request_finite_stop':
            from .hybrid_agent_stop_requests import dto
            return dto(self, rid, value, claim, private=private)
        result, status = self._source(claim) if claim is not None else (None, 'AWAITING_HUMAN')
        dto = {'schema_version': '1.0', 'request_id': rid, 'project_id': self.project_id,
            'data_mode': self.data_mode, 'store_epoch': self.store_epoch,
            'action': 'submit_goal', 'request_hash': digest(value),
            'submitted_by': value['actor'],
            'status': status,
            'execution_enabled': False, 'result': result}
        if private:
            dto['proposal'] = value['proposal']
            dto['expected_revision'] = value['expected_revision']
            dto['forward_expected_version'] = claim['expected_state_version'] if claim is not None else None
            dto['forwarded_by'] = claim['actor'] if claim is not None else None
        return dto

    def get(self, rid, *, token, method):
        self._identity()
        validate_schema(ID, rid)
        access = self._authorize(token, method)
        with self._db() as db:
            value, claim = self._decode(self._rows(db, rid=rid))
        if method == 'request' and value['actor']['id'] != access.principal.id:
            raise ControlError(404, 'NOT_FOUND', 'request not found')
        self._scope_access(value, access, method)
        dto = self._dto(rid, value, claim, private=method == 'session')
        self._scope_access(value, self._authorize(token, method), method)
        return dto

    @staticmethod
    def _scope_access(value, access, method):
        if value['action'] == 'request_finite_stop':
            from .hybrid_agent_stop_requests import allowed
            if not allowed(access.principal, value, human=method == 'session'):
                raise ControlError(404, 'NOT_FOUND', 'request not found')

    def list(self, *, token):
        self._identity()
        self._authorize(token, 'session')
        with self._db() as db:
            rows = self._rows(db)
            if len(rows) > MAX_ROWS:
                raise Conflict('inbox exceeds request limit')
            budget = ReadBudget(None, 16 * 1024 * 1024)
            values = [(row['id'], *self._decode(row, budget)) for row in rows]
        access = self._authorize(token, 'session')
        from .hybrid_agent_stop_requests import allowed
        visible = [(rid, value, claim) for rid, value, claim in values
                   if value['action'] != 'request_finite_stop' or allowed(access.principal, value, human=True)]
        items = [self._dto(rid, value, claim) for rid, value, claim in visible]
        access = self._authorize(token, 'session')
        for _, value, _ in visible: self._scope_access(value, access, 'session')
        return {'project_id': self.project_id, 'data_mode': self.data_mode, 'store_epoch': self.store_epoch, 'items': items}

    def forward(self, rid, *, request_hash, expected_version, token, csrf, origin):
        self._identity()
        if origin != self.origin:
            raise PermissionError('same-origin human forwarding required')
        validate_schema(ID, rid)
        validate_schema(HASH, request_hash)
        if type(expected_version) is not int or not 0 <= expected_version <= 2**63 - 1:
            raise ProtocolError('explicit current core version required')
        with self._db(write=True) as db:
            with self.auth.operator_guard(token, project_id=self.project_id, csrf=csrf) as guard:
                principal = guard.check().principal
                value, claim = self._decode(self._rows(db, rid=rid))
                if value['action'] != 'propose_goal_draft':
                    raise RequestConflict('finite STOP requires explicit original-scope forwarding')
                if digest(value) != request_hash:
                    raise RequestConflict('human confirmation differs from saved request')
                actor = {'id': principal.id, 'kind': 'human'}
                if claim is None:
                    key = 'forward_' + rid[8:]
                    claim = {**value, 'actor': actor, 'idempotency_key': key,
                        'expected_state_version': expected_version,
                        'control_command_id': control_command_key(actor, self.project_id, self.data_mode, key)}
                    validate_request(claim)
                    db.execute('UPDATE requests SET claim=? WHERE id=? AND claim IS NULL', (canonical(claim).decode(), rid))
                elif claim['actor'] != actor or claim['expected_state_version'] != expected_version:
                    raise RequestConflict('forwarding actor/body/version already frozen; reconcile original request')
                self._pure()
                guard.check()
                db.commit()
        # Two domains, not a fictitious distributed atomic transaction. No
        # token/CSRF is persisted. Original DraftService rechecks live human
        # authority at its actual writer commit; retry uses EXACT frozen key.
        source, status = self._source(claim)
        if status == 'STALE':
            raise RequestConflict('original frozen command is stale and was not accepted; submit a new explicit request')
        if source is None:
            self.drafts.submit(claim['proposal'], token=token, csrf=csrf, origin=origin,
                idempotency_key=claim['idempotency_key'], expected_revision=claim['expected_revision'],
                expected_state_version=claim['expected_state_version'], _control_command_id=claim['control_command_id'])
        return self.get(rid, token=token, method='session')


def install(app, services, controls, projects, auth, *, origin, max_jobs, delivery_readers=None):
    """Explicit trusted hosting only; no HTTP service/path/credential provision."""
    from fastapi import Request
    from .hybrid_control import ControlPool, body, error_response
    from contextlib import asynccontextmanager
    import asyncio
    services = dict(services)
    if not 1 <= len(services) <= 128:
        raise ValueError('bounded original request services required')
    for key, service in services.items():
        pair, project = controls.get(key), projects.get(key)
        if (type(service) is not AgentRequestService or pair is None or project is None
                or service.drafts is not pair.drafts or service.auth is not auth
                or (service.project_id, service.data_mode, service.origin) != (key, project.data_mode, origin)
                or service.store.root != Path(project.root).resolve(strict=True)):
            raise ValueError('request service original control binding mismatch')
        service._pure()
    pool = ControlPool(max_jobs)
    from .hybrid_contract_discovery import ContractDiscovery
    discoveries={key:ContractDiscovery(service,controls[key]) for key,service in services.items()}
    from .hybrid_client_execution_report import ExecutionReport
    reports={}
    for (project,kind),reader in dict(delivery_readers or {}).items():
        if project in discoveries:
            if kind not in ('CPU_TRIAL','ENGINEERING') or reader.kind!=kind:
                raise ValueError('original client report kind required')
            reports[(project,kind)]=ExecutionReport(discoveries[project],reader)
    discovery_pool=ControlPool(2)
    stop_prepare_pool = ControlPool(2)
    stop_read_pool = ControlPool(2)
    stop_tasks = set()
    stop_closing = [False]
    async def drain_stop_tasks():
        stop_closing[0] = True
        if stop_tasks:
            await asyncio.gather(*tuple(stop_tasks), return_exceptions=True)
    app.state.agent_request_stop_drain = drain_stop_tasks
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(current):
        async with original_lifespan(current):
            try:
                yield
            finally:
                await drain_stop_tasks()
                await pool.close()
                await stop_prepare_pool.close()
                await stop_read_pool.close()
                await discovery_pool.close()
    app.router.lifespan_context = lifespan

    def scoped(request, project, *, human=False):
        service = services.get(project)
        if service is None:
            raise ControlError(404, 'NOT_FOUND', 'request inbox not enabled')
        service._identity()
        authorization = request.headers.get('authorization')
        if authorization:
            if human:
                raise ControlError(403, 'PERMISSION_DENIED', 'human session required')
            prefix, _, token = authorization.partition(' ')
            access = auth.resolve(token, 'request') if prefix == 'Bearer' else None
            method = 'request'
        else:
            token, method = request.cookies.get('rlflow_session'), 'session'
            access = auth.resolve(token, method)
        if access is None:
            raise ControlError(401, 'AUTH_REQUIRED', 'live scoped inbox authentication required')
        if not access.principal.allows(project):
            raise ControlError(404, 'NOT_FOUND', 'request inbox not found')
        if method == 'session' and (access.principal.kind != 'human' or not access.principal.allows(project, 'operator')):
            raise ControlError(403, 'PERMISSION_DENIED', 'human operator required')
        return service, token, method

    def closed(request, *, write=False):
        if request.query_params:
            raise ControlError(400, 'VALIDATION_ERROR', 'closed inbox query required')
        headers = request.scope['headers']
        for name in (b'x-csrf-token', b'content-type', b'idempotency-key', b'origin', b'cookie', b'authorization'):
            if sum(k == name for k, _ in headers) > 1:
                raise ControlError(403, 'PERMISSION_DENIED', 'ambiguous inbox headers')
        if write and request.headers.get('origin') != origin:
            raise ControlError(403, 'PERMISSION_DENIED', 'same-origin inbox write required')

    async def response(call, *, jobs=pool):
        try:
            return await jobs.run(call)
        except ControlError as error:
            return error_response(error)
        except PermissionError:
            return error_response(ControlError(403, 'PERMISSION_DENIED', 'original scoped authorization required'))
        except ProtocolError:
            return error_response(ControlError(400, 'VALIDATION_ERROR', 'closed valid inbox payload required'))
        except RequestConflict:
            return error_response(ControlError(409, 'VERSION_CONFLICT', 'request/body/source conflict; reconcile original request'))
        except Conflict:
            return error_response(ControlError(503, 'UNKNOWN_EXECUTION', 'original source unavailable; reconcile without changing the request'))
        except Exception:
            return error_response(ControlError(503, 'UNKNOWN_EXECUTION', 'request result unknown; read the same request, do not create a new command'))

    @app.post('/api/v1/projects/{project_id}/agent-requests')
    async def submit(request: Request, project_id: str):
        try:
            closed(request, write=True)
            payload = await body(request)
            from .hybrid_agent_stop_requests import ACTION, SCOPE
            validate_schema({'oneOf': [obj({'action': {'const': 'submit_goal'}, 'proposal': {'type': 'object'}, 'expected_revision': COUNT}),
                obj({'action': {'const': ACTION}, 'stop_scope': SCOPE})]}, payload)
            validate_schema(ID, request.headers.get('idempotency-key'))
        except (ControlError, ProtocolError) as error:
            return error_response(error if isinstance(error, ControlError) else ControlError(400, 'VALIDATION_ERROR', 'closed goal request required'))
        def call():
            service, token, method = scoped(request, project_id)
            if method != 'request':
                raise ControlError(403, 'PERMISSION_DENIED', 'request-only agent token required')
            if payload['action'] == 'request_finite_stop':
                if service.stop_requests is None:
                    raise ControlError(409, 'UNSUPPORTED_CAPABILITY', 'original finite STOP requests not enabled')
                return service.stop_requests.submit(payload['stop_scope'], token=token, key=request.headers['idempotency-key'])
            return service.submit(payload['proposal'], token=token, idempotency_key=request.headers['idempotency-key'], expected_revision=payload['expected_revision'])
        return await response(call)

    @app.get('/api/v1/projects/{project_id}/proposal-contract')
    async def discovery(request:Request,project_id:str):
        def call():
            closed(request)
            _,token,method=scoped(request,project_id)
            return discoveries[project_id].read(token=token,method=method)
        return await response(call,jobs=discovery_pool)

    @app.get('/api/v1/projects/{project_id}/execution-report/{kind}/{source_id}')
    async def execution_report(request:Request,project_id:str,kind:str,source_id:str):
        def call():
            closed(request)
            _,token,method=scoped(request,project_id)
            report=reports.get((project_id,kind))
            if report is None:
                raise ControlError(409,'UNSUPPORTED_CAPABILITY','original delivery report not hosted')
            return report.read(source_id,token=token,method=method)
        return await response(call,jobs=discovery_pool)

    @app.post('/api/v1/projects/{project_id}/agent-requests/{request_id}/forward-stop')
    async def forward_stop(request: Request, project_id: str, request_id: str):
        try:
            closed(request, write=True)
            payload = await body(request)
            validate_schema(obj({'request_hash': HASH, 'resume_cleanup': {'type': 'boolean'}}), payload)
        except (ControlError, ProtocolError) as error:
            return error_response(error if isinstance(error, ControlError) else ControlError(400, 'VALIDATION_ERROR', 'explicit whole finite confirmation required'))
        def prepare():
            service, token, _ = scoped(request, project_id, human=True)
            helper = service.stop_requests
            if helper is None or getattr(app.state, 'finite_host_stop', None) is not helper.coordinator:
                raise ControlError(409, 'UNSUPPORTED_CAPABILITY', 'original finite STOP not hosted')
            batch = helper.prepare(request_id, **payload, token=token,
                csrf=request.headers.get('x-csrf-token'), origin=origin)
            return service, token, helper, batch
        async def execute():
            service, token, helper, batch = await stop_prepare_pool.run(prepare)
            if batch is not None:
                try:
                    await app.state.finite_host_stop_pool.run(lambda:helper.execute(batch, resume_cleanup=payload['resume_cleanup']))
                except ControlError:
                    helper.coordinator._safety_cancel()
                    raise
            return await stop_read_pool.run(lambda:service.get(request_id, token=token, method='session'))
        # Keep error mapping shared, but do NOT queue behind Goal forwards.
        try:
            # The bounded orchestration, not the HTTP waiter, owns the handoff
            # from a durable claim/all latches to the original STOP future.
            if stop_closing[0] or len(stop_tasks) >= 2:
                raise ControlError(429, 'BUDGET_EXHAUSTED', 'finite forwarding capacity reached')
            task = asyncio.create_task(execute())
            stop_tasks.add(task)
            def terminal(done):
                stop_tasks.discard(done)
                if not done.cancelled():
                    done.exception()  # Consume detached errors; never invent a receipt.
            task.add_done_callback(terminal)
            return await asyncio.shield(task)
        except ControlError as error:return error_response(error)
        except PermissionError:return error_response(ControlError(403, 'PERMISSION_DENIED', 'whole human finite scope required'))
        except RequestConflict:return error_response(ControlError(409, 'VERSION_CONFLICT', 'frozen finite request differs'))
        except Conflict:return error_response(ControlError(503, 'UNKNOWN_EXECUTION', 'original finite result unavailable'))
        except ProtocolError:return error_response(ControlError(400, 'VALIDATION_ERROR', 'closed finite request required'))
        except Exception:return error_response(ControlError(503, 'UNKNOWN_EXECUTION', 'finite result unknown; reconcile original request'))

    @app.get('/api/v1/projects/{project_id}/agent-requests')
    async def listing(request: Request, project_id: str):
        def call():
            closed(request)
            service, token, _ = scoped(request, project_id, human=True)
            return service.list(token=token)
        return await response(call)

    @app.get('/api/v1/projects/{project_id}/agent-requests/{request_id}')
    async def report(request: Request, project_id: str, request_id: str):
        def call():
            closed(request)
            service, token, method = scoped(request, project_id)
            return service.get(request_id, token=token, method=method)
        return await response(call)

    @app.post('/api/v1/projects/{project_id}/agent-requests/{request_id}/forward')
    async def forward(request: Request, project_id: str, request_id: str):
        try:
            closed(request, write=True)
            payload = await body(request)
            validate_schema(obj({'request_hash': HASH, 'expected_version': COUNT}), payload)
        except (ControlError, ProtocolError) as error:
            return error_response(error if isinstance(error, ControlError) else ControlError(400, 'VALIDATION_ERROR', 'explicit human confirmation required'))
        def call():
            service, token, _ = scoped(request, project_id, human=True)
            return service.forward(request_id, **payload, token=token,
                csrf=request.headers.get('x-csrf-token'), origin=origin)
        return await response(call)
