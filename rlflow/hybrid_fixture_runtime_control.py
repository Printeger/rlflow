"""Opt-in human control of the ONE original fixed CPU fixture owner.

Acceptance is the original phase CAS/event, not a second queue ledger. Start
retry only reads its receipt; Stop may continue original-cap safety cleanup.
"""
from contextlib import contextmanager, asynccontextmanager
from dataclasses import dataclass
import hmac
import json
import threading
import time
from urllib.parse import urlsplit

from .hybrid_budget_ledger import SECTIONS, entry_key
from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_fixture_runtime_ledger import CONTROL_BODY, control_command_id
from .hybrid_fixture_runtime_reads import FixtureTaskReader
from .hybrid_goals import digest, check_bytes
from .hybrid_protocol import ID, validate_schema
from .hybrid_reads import ReadBudget
from .store import Conflict, canonical
from .web_auth import AuthStore


@dataclass(eq=False)
class _Operation:
    command: dict
    token: str
    csrf: str
    lease: object
    thread: int
    accepted: bool = False
    guard: object = None
    db: object = None
    borrowed: bool = False


class FixtureRuntimeControlService:
    def __init__(self, runtime, auth, *, origin):
        if type(runtime) is not FixtureRuntimeOwner or type(auth) is not AuthStore:
            raise TypeError('actual protected Runtime and AuthStore required')
        parsed = urlsplit(origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or
                parsed.query or parsed.fragment or parsed.username):
            raise ValueError('canonical control origin required')
        with runtime.pool._lock, runtime._lock:
            runtime._actual()
            if runtime._control_service is not None or runtime.store._hybrid_auth_owner is not auth:
                raise Conflict('original Runtime/same approval AuthStore cannot be rebound')
            self.runtime, self.auth, self.origin = runtime, auth, origin
            self.project_id = runtime.workspace.project_id
            self.store_epoch = runtime.workspace.store_epoch
            self.store = runtime.store
            self.reader = FixtureTaskReader(self.store, project_id=self.project_id, store_epoch=self.store_epoch)
            self._local = threading.local(); self._issued = {}
            runtime._control_service = self

    def _operation(self):
        operation = getattr(self._local, 'operation', None)
        if operation is None: return None
        if (self._issued.get(id(operation)) is not operation or operation.thread != threading.get_ident() or
                self.runtime._control_service is not self):
            raise PermissionError('actual original control operation required')
        self.runtime._actual()
        return operation

    def _session(self, token, csrf):
        access = self.auth.resolve(token, 'session')
        if (access is None or access.principal.kind != 'human' or
                not access.principal.allows(self.project_id, 'operator') or
                type(csrf) is not str or not csrf.isascii() or not 20 <= len(csrf) <= 128 or
                access.csrf is None or not hmac.compare_digest(csrf, access.csrf)):
            raise PermissionError('live scoped human operator session required')
        return access

    @contextmanager
    def _borrow(self, db, *, cleanup):
        operation = self._operation()
        required = not cleanup or (operation is not None and
            operation.command['action'] == 'STOP_FIXED_SCOPE' and not operation.accepted)
        if not required:
            yield
            return
        if (operation is None or operation.borrowed or db is None or not db.in_transaction or
                not self.runtime.pool._lock._is_owned()):
            raise PermissionError('original command at actual owned writer required')
        with self.auth.operator_guard(operation.token, project_id=self.project_id, csrf=operation.csrf) as guard:
            operation.guard, operation.db, operation.borrowed = guard, db, True
            try:
                self._check_authority(cleanup=cleanup)
                yield
            finally:
                operation.guard = operation.db = None; operation.borrowed = False

    def _check_authority(self, *, cleanup, attempt=None):
        operation = self._operation()
        required = not cleanup or (operation is not None and
            operation.command['action'] == 'STOP_FIXED_SCOPE' and not operation.accepted)
        if not required: return
        if (operation is None or not operation.borrowed or operation.db is None or
                not operation.db.in_transaction):
            raise PermissionError('live original operation writer guard required')
        if attempt is not None and operation.lease is not attempt['lease']:
            raise PermissionError('actual operation and runtime scope differ')
        access = self.auth.check_operator_guard(operation.guard, project_id=self.project_id)
        if access.principal.id != operation.command['actor_id']:
            raise PermissionError('actual command actor differs')

    def _accepting_command(self, attempt, phase, version):
        operation = self._operation()
        if operation is None: return None  # protected owner safety shutdown
        expected_phase = 'HANDOFF_UNKNOWN' if operation.command['action'] == 'START_FIXED_CPU' else 'STOP_REQUESTED'
        if phase != expected_phase: return None
        if operation.lease is not attempt['lease'] or operation.command['task_id'] != attempt['origin']['task_id']:
            raise PermissionError('original operation Task/Attempt/Lease differs')
        if operation.command['expected_state_version'] != version:
            raise Conflict('fixture command stale expected version')
        self._check_authority(cleanup=phase == 'STOP_REQUESTED')
        return operation.command

    def _dispatch_entry(self, lease):
        operation = self._operation()
        if (operation is None or operation.lease is not lease or
                operation.command['action'] != 'START_FIXED_CPU'):
            raise PermissionError('actual issued Start operation required; no direct bound dispatch')

    def _check_fact(self, attempt, value):
        operation = self._operation()
        if operation is None: return  # safety/ACK cannot grant new execution
        name = 'start_command' if operation.command['action'] == 'START_FIXED_CPU' else 'stop_command'
        if operation.lease is not attempt['lease'] or value['request']['fixture_runtime'].get(name) != operation.command:
            raise Conflict('fixture command idempotency differs from actual retained phase')

    def _committed(self, value):
        # Called only AFTER actual cleanup db.commit() succeeds, still under
        # the original writer/Auth locks. Safety continuation is not a grant.
        operation = self._operation()
        if (operation is not None and value['request']['fixture_runtime']['phase'] == 'STOP_REQUESTED' and
                value['request']['fixture_runtime'].get('stop_command') == operation.command):
            operation.accepted = True

    def _source_key(self, command_id):
        return entry_key({'project_id': self.project_id, 'data_mode': 'fixture', 'idempotency_key': command_id})

    def receipt(self, command_id):
        validate_schema(ID, command_id)
        with self.reader.snapshot() as (db, meta):
            read = ReadBudget(db, 16*1024**2); key = self._source_key(command_id)
            if read.object(SECTIONS[0], key) is None: return None
            value = self.reader._point(db, read, key, meta['as_of_state_version'])
            runtime = value['request'].get('fixture_runtime')
            if runtime is None: raise Conflict('fixture command original phase absent')
            name = {'HANDOFF_UNKNOWN':'start_command', 'STOP_REQUESTED':'stop_command'}.get(runtime['phase'])
            command = runtime.get(name) if name is not None else None
            if command is None or command['command_id'] != command_id:
                raise Conflict('fixture command original acceptance differs')
            return {'schema_version':'1.1', 'command_id':command_id, 'action':command['action'],
                'status':'ACCEPTED', 'accepted_state_version':value['accepted_state_version'],
                'request_hash':command['request_hash'], 'actor_id':command['actor_id'],
                'task_id':command['task_id'], 'recorded_phase':runtime['phase'],
                'execution_status':'UNKNOWN', 'native_execution_enabled':False,
                'arbitrary_tree_stop':False, 'duplicate':False}

    def execute(self, body, *, token, csrf, origin, idempotency_key):
        self.runtime._actual()  # deny fork/dead owner BEFORE inherited Auth locks
        check_bytes(body, 4096); validate_schema(CONTROL_BODY, body); validate_schema(ID, idempotency_key)
        body = json.loads(canonical(body))  # retain exact immutable request value
        if origin != self.origin: raise PermissionError('same-origin fixture command required')
        access = self._session(token, csrf)
        binding = {'project_id':self.project_id, 'data_mode':'fixture', 'store_epoch':self.store_epoch}
        command_id = control_command_id(binding, access.principal.id, idempotency_key)
        command = {**body, 'actor_id':access.principal.id, 'idempotency_key':idempotency_key,
                   'command_id':command_id, 'request_hash':digest(body)}
        if self._operation() is not None: raise Conflict('nested fixture command refused')
        with self.runtime.pool._lock:
            self.runtime._actual()
            # A retry is freshly authenticated under an actual writer guard,
            # but performs NO Runtime phase, Popen, G or TTL renewal.
            with self.store.lock(), self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                with self.auth.operator_guard(token, project_id=self.project_id, csrf=csrf) as guard:
                    actual = self.auth.check_operator_guard(guard, project_id=self.project_id)
                    if actual.principal.id != command['actor_id']: raise PermissionError('actual actor differs')
                    existing = self.receipt(command_id)
                    if existing is not None:
                        if existing['request_hash'] != command['request_hash'] or existing['actor_id'] != command['actor_id']:
                            raise Conflict('fixture command idempotency key reused')
                        self.auth.check_operator_guard(guard, project_id=self.project_id)
                        if body['action'] == 'START_FIXED_CPU': return {**existing, 'duplicate':True}
            attempts = [a for a in self.runtime._attempts.values() if a['origin']['task_id'] == body['task_id']]
            if len(attempts) != 1: raise PermissionError('original current Task owner unavailable')
            attempt = attempts[0]; lease = attempt['lease']
            current_runtime = self.runtime._current(attempt)['fixture_runtime']
            current = current_runtime['phase']
            if body['action'] == 'START_FIXED_CPU' and current != 'REGISTER_NO_HANDOFF':
                raise Conflict('fixture Task already dispatched or stopped; no command backfill')
            if existing is not None:
                if (current not in ('STOP_REQUESTED', 'FIXTURE_SCOPE_STOPPED') or
                        current_runtime.get('stop_command') != command):
                    raise Conflict('fixture original accepted STOP scope differs')
            elif body['action'] == 'STOP_FIXED_SCOPE' and current in ('STOP_REQUESTED', 'FIXTURE_SCOPE_STOPPED'):
                raise Conflict('fixture Task already safety-stopped; no command backfill')
            operation = _Operation(command, token, csrf, lease, threading.get_ident())
            # Only the original whole accepting event AND matching actual
            # retained lease/current lineage above can authorize continuation.
            # No copied DTO, new command, session renewal or historical owner.
            operation.accepted = existing is not None
            self._issued[id(operation)] = operation; self._local.operation = operation
            try:
                try:
                    if body['action'] == 'START_FIXED_CPU':
                        self.runtime.start(lease)
                    else:
                        self.runtime.stop_to_terminal(lease)
                except Exception:
                    # Never turn lost COMMIT return into a repeated dispatch.
                    # If accepted, return its original fact, not guessed success.
                    original = self.receipt(command_id)
                    if original is None: raise
                    return {**original, 'duplicate':existing is not None}
                original = self.receipt(command_id)
                if original is None: raise Conflict('fixture command COMMIT receipt missing')
            finally:
                self._issued.pop(id(operation), None); self._local.operation = None
        if body['action'] == 'START_FIXED_CPU':
            # ONE finite observer of the already released fixed child. This
            # does not schedule new work and needs no human session to record
            # genuine ACK after expiry. GET remains strictly read-only.
            deadline = time.monotonic()+4
            while time.monotonic()<deadline:
                try: value = self.runtime.poll(lease)
                except Exception: break  # original acceptance remains UNKNOWN
                if value['phase'] != 'RELEASE_INTENT': break
                time.sleep(.01)
        return {**original, 'duplicate':existing is not None}


def install(app, services, projects, auth, *, origin, max_jobs):
    from pathlib import Path
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlPool, ControlError, body, error_response
    from .hybrid_protocol import ProtocolError

    services = dict(services)
    if len(services)>128: raise ValueError('too many fixture control services')
    for key, service in services.items():
        project = projects.get(key)
        if (type(service) is not FixtureRuntimeControlService or project is None or project.data_mode != 'fixture' or
                service.project_id != key or service.auth is not auth or service.origin != origin or
                service.store.root != Path(project.root).resolve(strict=True) or
                service.runtime._control_service is not service):
            raise ValueError('original fixture control startup binding required')
        with service.reader.snapshot(): pass
    starts, stops = ControlPool(max_jobs), ControlPool(2)
    app.state.fixture_start_pool, app.state.fixture_stop_pool = starts, stops
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(current):
        async with original_lifespan(current):
            try: yield
            finally:
                await starts.close(); await stops.close()
    app.router.lifespan_context = lifespan

    def authorize(request, project_id, *, write=False):
        if write and project_id in services:
            services[project_id].runtime._actual()  # same early child boundary
        authorization = request.headers.get('authorization')
        if authorization and write: raise ControlError(403,'PERMISSION_DENIED','human session commands required')
        if authorization:
            prefix, _, token = authorization.partition(' ')
            access = auth.resolve(token, 'bearer') if prefix == 'Bearer' else None
        else:
            token = request.cookies.get('rlflow_session'); access = auth.resolve(token, 'session')
        if access is None: raise ControlError(401,'AUTH_REQUIRED','authentication required')
        if project_id not in services or not access.principal.allows(project_id):
            raise ControlError(404,'NOT_FOUND','project not found')
        if write and (access.principal.kind != 'human' or not access.principal.allows(project_id, 'operator')):
            raise ControlError(403,'PERMISSION_DENIED','scoped human operator required')
        return services[project_id], token

    async def respond(call, pool, status):
        try: return JSONResponse(await pool.run(call), status_code=status)
        except ControlError as error: return error_response(error)
        except PermissionError: return error_response(ControlError(403,'PERMISSION_DENIED','live original operator guard required'))
        except Conflict as error:
            if 'idempotency' in str(error): return error_response(ControlError(409,'IDEMPOTENCY_CONFLICT','fixture command key conflict'))
            if 'stale' in str(error) or 'already' in str(error):
                return error_response(ControlError(409,'VERSION_CONFLICT','fixture Task state conflict'))
            return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','fixture command source unavailable',True))
        except (ValueError, ProtocolError): return error_response(ControlError(400,'VALIDATION_ERROR','closed fixture command required'))
        except Exception: return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','fixture command outcome unavailable',True))

    @app.post('/api/v1/projects/{project_id}/fixture-tasks/{reservation_id}/commands')
    async def commands(request: Request, project_id: str, reservation_id: str):
        try:
            # A warm parent executor is not a child worker. Reject the dead
            # original Runtime BEFORE submitting to any inherited queue/lock.
            if project_id in services: services[project_id].runtime._actual()
            if request.query_params: raise ValueError('closed command query required')
            counts = {}
            for key, value in request.scope['headers']: counts[key] = counts.get(key, 0)+1
            if any(counts.get(k,0)>1 for k in (b'x-csrf-token',b'idempotency-key',b'content-type')):
                raise ControlError(403,'PERMISSION_DENIED','ambiguous command headers')
            if request.headers.get('origin') != origin or not request.headers.get('x-csrf-token'):
                raise ControlError(403,'PERMISSION_DENIED','same-origin session CSRF required')
            payload = await body(request); validate_schema(CONTROL_BODY, payload)
            validate_schema(ID, request.headers.get('idempotency-key')); validate_schema(ID, reservation_id)
        except PermissionError:
            return error_response(ControlError(403,'PERMISSION_DENIED','original Runtime owner unavailable'))
        except ControlError as error: return error_response(error)
        except (ValueError, ProtocolError): return error_response(ControlError(400,'VALIDATION_ERROR','closed fixture command required'))
        def execute():
            service, token = authorize(request, project_id, write=True)
            task = service.reader.task(reservation_id)
            if task is None or task['task']['id'] != payload['task_id']:
                raise ControlError(404,'NOT_FOUND','fixture Task not found')
            return service.execute(payload, token=token, csrf=request.headers['x-csrf-token'], origin=origin,
                                   idempotency_key=request.headers['idempotency-key'])
        return await respond(execute, stops if payload['action']=='STOP_FIXED_SCOPE' else starts, 202)

    @app.get('/api/v1/projects/{project_id}/fixture-commands/{command_id}')
    async def receipt(request: Request, project_id: str, command_id: str):
        def lookup():
            if request.query_params: raise ValueError('closed receipt query required')
            service, _ = authorize(request, project_id)
            result = service.receipt(command_id)
            authorize(request, project_id)
            if result is None: raise ControlError(404,'NOT_FOUND','fixture command not found')
            return result
        return await respond(lookup, starts, 200)
