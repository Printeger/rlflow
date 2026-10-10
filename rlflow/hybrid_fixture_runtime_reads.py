"""Indexed, read-only fixed CPU Task views. Historical facts are not leases.

No Runtime owner, Source poll, migration, reconciliation or process inspection.
The reservation key is the stable indexed selector, not an execution grant.
"""
from .hybrid_budget import account_key
from .hybrid_budget_ledger import (SECTIONS, EVENT, scope, derived_heads,
    expected_objects, validate_record)
from .hybrid_fixture_runtime_ledger import PHASES, validate_runtime
from .hybrid_goals import digest
from .hybrid_protocol import ID, validate_schema
from .hybrid_reads import HybridReader, ReadBudget
from .store import Conflict, Store


class FixtureTaskReader(HybridReader):
    _accepted_origin_kind = 'PROTOCOL_CONFORMANCE'
    def __init__(self, store, *, project_id, store_epoch):
        if type(store) is not Store:
            raise TypeError('actual existing Store required')
        super().__init__(store, project_id=project_id, data_mode='fixture', store_epoch=store_epoch)

    def _point(self, db, read, key, version):
        value = read.object(SECTIONS[0], key)
        if value is None:
            raise Conflict('fixture Task original fact missing')
        validate_record(SECTIONS[0], key, value)
        request = value['request']
        if ((request['project_id'], request['data_mode'], request['store_epoch']) !=
                (self.project_id, self.data_mode, self.store_epoch) or
                value['accepted_state_version'] > version):
            raise Conflict('fixture Task original scope or version differs')
        proof = self.store._budget_event(db, key, max_bytes=min(read.remaining, 1024**2),
                                        _parse=read.parse, _decode=read.decode)
        expected = ((EVENT, 'hybrid-core', account_key(scope(request)),
                     value['accepted_state_version']), expected_objects(value))
        if proof != expected:
            raise Conflict('fixture Task original whole event differs')
        return value

    def _head(self, db, read, key, version):
        head = read.object(SECTIONS[2], key)
        tip = self.store._budget_tip(db, version, reservation_id=key)
        if head is None:
            if tip is not None:
                raise Conflict('fixture Task indexed head missing')
            return None
        validate_record(SECTIONS[2], key, head)
        if (head['scope']['project_id'], head['scope']['data_mode']) != (self.project_id, self.data_mode):
            raise Conflict('fixture Task head scope differs')
        if (head['last_entry_key'], head['accepted_state_version']) != tip:
            raise Conflict('fixture Task head differs from original indexed tip')
        value = self._point(db, read, head['last_entry_key'], version)
        if derived_heads(value)[SECTIONS[2]].get(key) != head:
            raise Conflict('fixture Task head is not original derived head')
        if ('fixture_runtime' not in head or
                head['fixture_runtime']['origin']['kind'] != self._accepted_origin_kind):
            return None
        return head, value

    @staticmethod
    def _dto(key, head):
        runtime = head['fixture_runtime']; origin = runtime['origin']
        return {'id': origin['task_id'], 'attempt_id': origin['attempt_id'],
                'reservation_id': key, 'kind': 'PROTOCOL_CONFORMANCE',
                'authorization': 'LOCAL_PROTOCOL_ONLY', 'recorded_phase': runtime['phase'],
                'recorded_at_state_version': head['accepted_state_version'],
                'current_execution_status': 'UNKNOWN', 'controls_available': False,
                'source_coverage': 'ORIGINAL_EVENT_VERIFIED', 'model_enabled': False,
                'native_execution_enabled': False, 'candidate_write_enabled': False,
                'delegation_enabled': False, 'actual_cost_status': 'UNKNOWN',
                'synthetic_tokens_settled': False, 'arbitrary_tree_stop': False,
                'resource_release_status': 'NOT_OBSERVED',
                'recorded_wall_seconds': runtime['wall_seconds'] if runtime['phase'] == 'FIXTURE_SCOPE_STOPPED' else None}

    def tasks(self, *, after='', limit=10):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('bounded fixture Task page required')
        if after: validate_schema(ID, after)
        with self.snapshot() as (db, meta):
            self.store._require_budget_indices(db)
            read = ReadBudget(db, 16*1024**2)
            rows = list(db.execute("SELECT CASE WHEN typeof(object_key)='text' AND "
                                   "length(CAST(object_key AS BLOB))<=160 THEN object_key END AS bounded_key "
                                   'FROM projection WHERE section=? AND object_key>? '
                                   'AND object_key!=? ORDER BY object_key LIMIT ?',
                                   (SECTIONS[2], after, '', limit+1)))
            keys = []
            for row in rows:
                key = row['bounded_key']
                if type(key) is not str: raise Conflict('fixture Task source key exceeds bound')
                validate_schema(ID, key)
                keys.append(key)
            items = []
            for key in keys[:limit]:
                pair = self._head(db, read, key, meta['as_of_state_version'])
                if pair is not None: items.append(self._dto(key, pair[0]))
            # Cursor follows scanned reservation keys, including non-runtime
            # reservations. Sparse pages never hide later actual Tasks.
            return self.output({**meta, 'items': items,
                'next_after': keys[limit-1] if len(keys)>limit else None}, 64*1024)

    def task(self, reservation_id, *, timeline=False):
        validate_schema(ID, reservation_id)
        with self.snapshot() as (db, meta):
            self.store._require_budget_indices(db)
            read = ReadBudget(db, 16*1024**2)
            pair = self._head(db, read, reservation_id, meta['as_of_state_version'])
            if pair is None: return None
            head, value = pair
            result = {**meta, 'task': self._dto(reservation_id, head)}
            if timeline:
                chain = []; origin = head['fixture_runtime']['origin']; seen = set()
                for _ in PHASES:
                    request = value['request']; runtime = request['fixture_runtime']
                    key = self._key(value)
                    if (key in seen or request['reservation_id'] != reservation_id or
                            runtime['origin'] != origin):
                        raise Conflict('fixture Task bounded lineage differs')
                    seen.add(key)
                    validate_runtime(request, value['prior_reservation'])
                    chain.append({'event_id': key, 'state_version': value['accepted_state_version'],
                                  'recorded_at': value['recorded_at'], 'recorded_phase': runtime['phase']})
                    previous = runtime['previous']
                    if previous is None:
                        if runtime['phase'] != 'REGISTER_NO_HANDOFF':
                            raise Conflict('fixture Task registration missing')
                        break
                    prior = self._point(db, read, previous['key'], meta['as_of_state_version'])
                    if (digest(prior) != previous['hash'] or
                            derived_heads(prior)[SECTIONS[2]].get(reservation_id) != value['prior_reservation'] or
                            prior['accepted_state_version'] >= value['accepted_state_version']):
                        raise Conflict('fixture Task original predecessor differs')
                    value = prior
                else: raise Conflict('fixture Task lineage exceeds finite phase bound')
                result['events'] = list(reversed(chain))
            return self.output(result, 64*1024)

    @staticmethod
    def _key(value):
        from .hybrid_budget_ledger import entry_key
        return entry_key(value['request'])


def install(app, readers, projects, auth):
    """Trusted startup injection only; no caller-supplied roots or epochs."""
    from contextlib import asynccontextmanager
    from pathlib import Path
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlError, ControlPool, error_response
    from .hybrid_protocol import ProtocolError
    from .hybrid_local_cpu_reads import LocalCpuPublicTaskReader

    readers = dict(readers)
    if len(readers)>128: raise ValueError('too many fixture Task sources')
    for key, reader in readers.items():
        project = projects.get(key)
        if (type(reader) not in (FixtureTaskReader,LocalCpuPublicTaskReader) or project is None or project.data_mode != 'fixture' or
                reader.project_id != key or reader.store.root != Path(project.root).resolve(strict=True)):
            raise ValueError('fixture Task reader startup scope mismatch')
        with reader.snapshot(): pass

    # Independent of control/STOP capacity. Slots belong to the real worker,
    # including after its HTTP waiter disconnects, until source validation ends.
    pool = ControlPool(2)
    app.state.hybrid_fixture_read_pool = pool
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(current):
        async with original_lifespan(current):
            try: yield
            finally: await pool.close()
    app.router.lifespan_context = lifespan

    def authorize(request, project_id):
        authorization = request.headers.get('authorization')
        if authorization:
            prefix, _, token = authorization.partition(' ')
            access = auth.resolve(token, 'bearer') if prefix == 'Bearer' else None
        else: access = auth.resolve(request.cookies.get('rlflow_session'), 'session')
        if access is None: raise ControlError(401, 'AUTH_REQUIRED', 'authentication required')
        if project_id not in readers or not access.principal.allows(project_id):
            raise ControlError(404, 'NOT_FOUND', 'project not found')
        return readers[project_id]

    async def response(request, project_id, call):
        try:
            reader = authorize(request, project_id)
            def read():
                result = call(reader)
                if result is not None:
                    reader.check_current(result['as_of_state_version'])
                return result
            result = await pool.run(read)
            authorize(request, project_id)
            if result is None: raise ControlError(404, 'NOT_FOUND', 'fixture Task not found')
            return JSONResponse(result)
        except ControlError as error: return error_response(error)
        except Conflict:
            return error_response(ControlError(503, 'UNSUPPORTED_CAPABILITY', 'fixture Task source unavailable', True))
        except (ValueError, ProtocolError):
            return error_response(ControlError(400, 'VALIDATION_ERROR', 'bounded fixture Task query required'))
        except Exception:
            return error_response(ControlError(503, 'UNSUPPORTED_CAPABILITY', 'fixture Task source unavailable', True))

    @app.get('/api/v1/projects/{project_id}/fixture-tasks')
    async def tasks(request: Request, project_id: str):
        def query(reader):
            if (set(request.query_params)-{'after', 'limit'} or
                    any(len(request.query_params.getlist(k))!=1 for k in request.query_params)):
                raise ValueError('closed page query required')
            raw = request.query_params.get('limit', '10')
            if not raw.isascii() or not raw.isdecimal() or len(raw)>2:
                raise ValueError('integer page size required')
            return reader.tasks(after=request.query_params.get('after', ''), limit=int(raw))
        return await response(request, project_id, query)

    @app.get('/api/v1/projects/{project_id}/fixture-tasks/{reservation_id}')
    async def task(request: Request, project_id: str, reservation_id: str):
        def query(reader):
            if request.query_params: raise ValueError('closed Task query required')
            return reader.task(reservation_id)
        return await response(request, project_id, query)

    @app.get('/api/v1/projects/{project_id}/fixture-tasks/{reservation_id}/timeline')
    async def timeline(request: Request, project_id: str, reservation_id: str):
        def query(reader):
            if request.query_params: raise ValueError('closed Task timeline required')
            return reader.task(reservation_id, timeline=True)
        return await response(request, project_id, query)
