"""Read original finite budgets and Pool facts; never settle, poll or free.

The two original databases have independent versions and observation times.
Pool occupancy is a durable claim count, not active-process/GPU observation.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import stat

from .hybrid_budget import account_key, validate_balances
from .hybrid_budget_ledger import SECTIONS, derived_heads, validate_record
from .hybrid_goals import digest
from .hybrid_reads import ReadBudget
from .store import Conflict, canonical


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class FiniteAccounting:
    def __init__(self, host, controls):
        # Called only after the original finite app's full startup preflight.
        host._pure_identity()
        self.host = host
        self.services = {s.project_id: s for s in controls}
        self._signature = tuple((s, s.store, s.reader, s.project_id, s.store_epoch,
            s.reservation_id, s.task_id, s.runtime, s.unit, s.auth, s.runtime.membership) for s in controls)
        self._scopes = {s.project_id: {k: s._registration['request'][k]
            for k in ('project_id', 'data_mode', 'goal_ref')} for s in controls}
        self._stores = tuple((s.store, s.store.root, s.store.db, s.store._existing_identity,
            s.store._existing_lock_identity, getattr(s.store, 'store_epoch', None), canonical(s._registration)) for s in controls)
        self._pins = tuple((p, p.lstat().st_dev, p.lstat().st_ino, stat.S_IFMT(p.lstat().st_mode))
            for s in controls for p in (s.store.root, s.store.root/'runtime', s.store.db, s.store.root/'runtime/writer.lock'))
        self._host = host
        self._pool = host.pool

    def _pure(self):
        # Parent identity precedes inherited Auth/executor/Store/Pool locks.
        if self.host is not self._host or self.host.pool is not self._pool:
            raise PermissionError('original finite accounting host required')
        self.host._pure_identity()
        for (store, root, db, identity, lock_identity, epoch, registration), row in zip(self._stores, self._signature):
            if (store.root, store.db, store._existing_identity, store._existing_lock_identity, getattr(store, 'store_epoch', None)) != (root, db, identity, lock_identity, epoch) or canonical(row[0]._registration) != registration:
                raise PermissionError('original accounting Store or registration rebound')
        if set(self.services) != set(self._scopes):
            raise PermissionError('original accounting projects changed')
        for s, store, reader, project, epoch, reservation, task, runtime, unit, auth, membership in self._signature:
            if (self.services.get(project) is not s or s.host is not self.host or
                (s.store, s.reader, s.project_id, s.store_epoch, s.reservation_id, s.task_id,
                 s.runtime, s.unit, s.auth, s.runtime.membership) != (store, reader, project, epoch, reservation, task, runtime, unit, auth, membership) or
                s.runtime.pool is not self._pool or reader.store is not store or
                (reader.project_id, reader.data_mode, reader.store_epoch) != (project, 'fixture', epoch)):
                raise PermissionError('original finite accounting binding changed')

    def _physical(self):
        for path, device, inode, kind in self._pins:
            info = path.lstat()
            if (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)) != (device, inode, kind) or info.st_mode & 0o077 or kind == stat.S_IFREG and info.st_nlink != 1:
                raise Conflict('original accounting filesystem identity changed')

    def _budget(self, service):
        reader = service.reader
        with reader.snapshot() as (db, meta):
            service.store._require_budget_indices(db)
            read = ReadBudget(db, 16*1024**2)
            pair = reader._head(db, read, service.reservation_id, meta['as_of_state_version'])
            if pair is None or pair[0]['fixture_runtime']['origin']['task_id'] != service.task_id:
                raise Conflict('original finite accounting task missing')
            reservation = pair[0]
            scope = reservation['scope']
            if scope != self._scopes[service.project_id]:
                raise Conflict('original finite accounting Goal scope changed')
            key = account_key(scope)
            head = read.object(SECTIONS[1], key)
            if head is None:
                raise Conflict('original Goal budget head missing')
            validate_record(SECTIONS[1], key, head)
            tip = service.store._budget_tip(db, meta['as_of_state_version'], goal_account_key=key)
            if (head['last_entry_key'], head['accepted_state_version']) != tip:
                raise Conflict('original Goal budget head differs from indexed tip')
            entry = reader._point(db, read, head['last_entry_key'], meta['as_of_state_version'])
            if derived_heads(entry)[SECTIONS[1]].get(key) != head or head['scope'] != scope:
                raise Conflict('Goal budget is not original derived head')
            validate_balances(head['balance'])
            return {**meta, 'task_id': service.task_id, 'reservation_id': service.reservation_id,
                'goal_ref': scope['goal_ref'], 'budget': {
                    'profile': 'ORIGINAL_GOAL_LEDGER_INT64_DECIMAL', 'observed_at': _now(),
                    'entry_id': head['last_entry_key'], 'entry_sha256': digest(entry),
                    'recorded_state_version': head['accepted_state_version'],
                    'reservation_status': reservation['status'],
                    'reservation_recorded_state_version': reservation['accepted_state_version'],
                    'balances': {name: {k: str(v) for k, v in row.items()} for name, row in head['balance'].items()},
                    'actual_cost_status': 'UNKNOWN', 'source_coverage': 'ORIGINAL_EVENT_VERIFIED'}}

    def _occupancy(self, service):
        pool = self._pool
        # Original protected Pool snapshot connector; no append/claim/free.
        # Not concurrent with the project's budget transaction.
        with pool._transaction() as db:
            version, heads = pool._state(db)
            rows = db.execute("SELECT CASE WHEN typeof(id)='text' AND length(CAST(id AS BLOB))<=160 THEN id END FROM members LIMIT 65").fetchall()
            if len(rows)>64:
                raise Conflict('finite Pool member bound exceeded')
            projects = []
            for row in rows:
                original = pool._member_point(db, row[0])
                if original is None:
                    raise Conflict('original Pool member source missing')
                projects.append(original['payload']['project_id'])
            occupied = project_occupied = 0
            for head in heads:
                if head is None or head['state'] == 'FREE':
                    continue
                occupied += 1
                claim = pool._point(db, head['claim_key'])
                if claim['payload']['member_id'] == service.runtime.membership.id:
                    project_occupied += 1
            return {'profile': 'ORIGINAL_DURABLE_SHARED_POOL', 'pool_id': pool.binding['pool_id'],
                'as_of_pool_version': version, 'observed_at': _now(), 'capacity': 3,
                'project_occupied': project_occupied, 'occupied': occupied,
                'coverage': 'ALL_REGISTERED_PROJECTS', 'execution_enabled': False,
                'release_enabled': False, 'process_status': 'NOT_OBSERVED'}, tuple(projects)

    def read(self, project_id):
        self._pure()
        self._physical()
        service = self.services[project_id]
        result = self._budget(service)
        pool, projects = self._occupancy(service)
        service.reader.check_current(result['as_of_state_version'])
        self._pure()
        self._physical()
        return {**result, 'profile': 'ORIGINAL_FINITE_ACCOUNTING', 'pool': pool,
            'cross_database_atomic': False, 'goal_completed': False}, projects


def install(app, source, auth):
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlPool, ControlError, error_response
    jobs = ControlPool(2)
    app.state.finite_accounting_source = source
    app.state.finite_accounting_pool = jobs
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current):
        async with original(current):
            try: yield
            finally: await jobs.close()
    app.router.lifespan_context = lifespan

    def authorize(request, project_id):
        source._pure()
        authorization = request.headers.get('authorization')
        if authorization:
            prefix, _, token = authorization.partition(' ')
            access = auth.resolve(token, 'bearer') if prefix == 'Bearer' else None
        else:
            access = auth.resolve(request.cookies.get('rlflow_session'), 'session')
        if access is None:
            raise ControlError(401, 'AUTH_REQUIRED', 'authentication required')
        if project_id not in source.services or not access.principal.allows(project_id):
            raise ControlError(404, 'NOT_FOUND', 'project not found')
        return access

    @app.get('/api/v1/projects/{project_id}/finite-accounting')
    async def accounting(request: Request, project_id: str):
        try:
            authorize(request, project_id)
            if request.query_params:
                raise ControlError(400, 'VALIDATION_ERROR', 'closed accounting query required')
            result, projects = await jobs.run(lambda: source.read(project_id))
            access = authorize(request, project_id)
            if not all(access.principal.allows(p) for p in projects):
                result['pool']['occupied'] = None
                result['pool']['as_of_pool_version'] = None
                result['pool']['coverage'] = 'PROJECT_ONLY'
            return JSONResponse(result)
        except ControlError as error:
            return error_response(error)
        except PermissionError:
            return error_response(ControlError(403, 'PERMISSION_DENIED', 'original accounting source required'))
        except Exception:
            return error_response(ControlError(503, 'UNSUPPORTED_CAPABILITY', 'original accounting source unavailable', True))
