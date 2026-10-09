"""Human control of one existing original finite CPU experiment Unit.

No cold adoption, new grant, scheduler, Controller renewal or paid resource.
RUN acceptance is original HANDOFF; emergency STOP intent is independent of
already-completed safety cleanup. Both share one immutable command namespace.
"""
from contextlib import contextmanager
from contextlib import asynccontextmanager
import json
import os
import threading
from urllib.parse import urlsplit

from .hybrid_budget_ledger import SECTIONS as BUDGET, entry_key
from .hybrid_cpu_execution_unit import CpuTrialExecutionUnit
from .hybrid_cpu_trial import KIND, AUTHORIZATION
from . import hybrid_cpu_unit_stop as cpu_stop
from .hybrid_fixture_runtime_control import FixtureRuntimeControlService, _Operation
from .hybrid_fixture_runtime_ledger import CONTROL_BODY, control_command_id
from .hybrid_fixture_runtime_reads import FixtureTaskReader
from .hybrid_host_execution import HostExecutionService
from .hybrid_goals import digest, check_bytes
from .hybrid_protocol import ID, validate_schema, ProtocolError
from .hybrid_reads import ReadBudget
from .store import Conflict, canonical
from .web_auth import AuthStore


class CpuUnitTaskReader(FixtureTaskReader):
    _accepted_origin_kind = KIND

    @staticmethod
    def _dto(key,head):
        return {**FixtureTaskReader._dto(key,head),'kind':KIND,'authorization':AUTHORIZATION}


class _StopGuard:
    def __init__(self,service,db,read,auth_guard,value):
        self.service,self.db,self.read,self.auth_guard=service,db,read,auth_guard
        self.raw=canonical(value);self.thread=threading.get_ident()

    def check(self):self.service.check_stop_guard(self.db,self)

    def lookup(self,section,key):
        value=self.read.object(section,key)
        if not key:
            populated=self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone()
            if populated and value!={}:raise Conflict('CPU stop original marker missing or differs')
        return value


class _OriginalUnitControl(FixtureRuntimeControlService):
    _start_body = CONTROL_BODY
    _unit_type = CpuTrialExecutionUnit
    _reader_type = CpuUnitTaskReader
    _stop_domain = cpu_stop
    _start_action = 'START_FIXED_CPU'
    _stop_action = 'CANCEL_FIXED_CPU_TRIAL'
    _profile = 'FIXED_CPU_PI_TRIAL_UNIT'
    _store_slot = '_hybrid_cpu_unit_control_service'
    _store_bind = 'bind_hybrid_cpu_unit_control'
    _store_proof = '_cpu_unit_stop_event'

    def __init__(self,host,lease,auth,*,origin):
        if type(host) is not HostExecutionService or type(auth) is not AuthStore:
            raise TypeError('original finite Host and same AuthStore required')
        unit=host._unit(lease)
        if type(unit) is not self._unit_type:raise TypeError('original CPU trial Unit required')
        runtime=unit.runtime;parsed=urlsplit(origin)
        if (parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or
                parsed.path or parsed.query or parsed.fragment):raise ValueError('canonical control origin required')
        with runtime.pool._lock,runtime._lock:
            attempt=unit._actual()
            if (runtime._control_service is not None or runtime.store._hybrid_auth_owner is not auth or
                    unit._request is not None or unit._cancelled.is_set() or
                    runtime._current(attempt)['fixture_runtime']['phase']!='REGISTER_NO_HANDOFF' or
                    getattr(runtime.store,self._store_slot) is not None):
                raise Conflict('one original undispatched CPU Unit control binding required')
            self.host,self.unit,self.runtime,self.auth,self.origin=host,unit,runtime,auth,origin
            self.store=runtime.store;self.project_id=runtime.workspace.project_id;self.store_epoch=runtime.workspace.store_epoch
            self.reader=self._reader_type(self.store,project_id=self.project_id,store_epoch=self.store_epoch)
            self._local=threading.local();self._issued={};self._operation_raw={};self._stop_guards={};self._pending_stops={}
            self._intents={};self._intent_lock=threading.Lock();self._start_intent=None
            self._registration=attempt['entries']['REGISTER_NO_HANDOFF']
            self.task_id=attempt['origin']['task_id']
            self.reservation_id=attempt['ready']['source_context']['budget_reservation']['reservation_id']
            # Bounded protected startup census of this command namespace. It
            # detects old keys before a new emergency latch, never adopts caps.
            with self.store.read_connection() as db:
                keys=list(db.execute('SELECT idempotency_key FROM events WHERE idempotency_key>=? AND idempotency_key<? '
                    'ORDER BY idempotency_key LIMIT 33',('fixture_command_','fixture_command'+chr(96))))
            if len(keys)>32:raise Conflict('finite CPU command history capacity reached')
            for row in keys:
                receipt=self.receipt(row[0])
                if receipt is None:raise Conflict('original command namespace source unavailable')
                self._intents[row[0]]={'hash':receipt['request_hash'],'actor':receipt['actor_id'],
                    'task':receipt['task_id'],'dispatch_entered':True}
            getattr(self.store,self._store_bind)(self)
            runtime._control_service=self

    def _pure(self):
        self.host._pure_identity();self.unit._pure_identity()
        if (self.host._unit(self.unit.lease) is not self.unit or self.runtime._control_service is not self or
                getattr(self.store,self._store_slot) is not self):
            raise PermissionError('actual original CPU control required')

    def _operation(self):
        operation=super()._operation()
        if operation is not None and self._operation_raw.get(id(operation))!=canonical(operation.command):
            raise PermissionError('original immutable CPU control operation required')
        return operation

    def _check_final_authority(self,*,cleanup,attempt=None):
        self._pure()
        operation=getattr(self._local,'operation',None)
        if operation is not None and self._operation_raw.get(id(operation))!=canonical(operation.command):
            raise PermissionError('final immutable original Unit command required')
        return super()._check_final_authority(cleanup=cleanup,attempt=attempt)

    def _unit_handoff(self,unit,version):
        self._pure();operation=self._operation()
        if (unit is not self.unit or operation is None or operation.command['action']!=self._start_action or
                operation.command['task_id']!=self.task_id or operation.lease is not unit.lease or
                unit._request!={'idempotency_key':operation.command['command_id'],'expected_state_version':version} or
                operation.command['expected_state_version']!=version):
            raise PermissionError('original human command and CPU unit HANDOFF required')
        self._check_authority(cleanup=False,attempt=self.runtime._leases[id(unit.lease)])
        return operation.command['command_id']

    def _dispatch_entry(self,lease):
        operation=self._operation()
        if operation is None or operation.lease is not lease or operation.command['action']!=self._start_action:
            raise PermissionError('actual issued original Unit Start required')

    def _accepting_command(self,attempt,phase,version):
        operation=self._operation()
        if operation is not None and operation.command['action']==self._stop_action:return None
        if operation is None or phase!='HANDOFF_UNKNOWN':return None
        if (operation.lease is not attempt['lease'] or operation.command['task_id']!=attempt['origin']['task_id'] or
                operation.command['action']!=self._start_action):
            raise PermissionError('original Unit accepting command scope differs')
        if operation.command['expected_state_version']!=version:raise Conflict('Unit command stale expected version')
        self._check_authority(cleanup=False,attempt=attempt)
        return operation.command

    def _check_fact(self,attempt,value):
        operation=self._operation()
        if operation is not None and operation.command['action']==self._stop_action:return
        if operation is not None and (operation.lease is not attempt['lease'] or
                value['request']['fixture_runtime'].get('start_command')!=operation.command):
            raise Conflict('Unit original command retained phase differs')

    @contextmanager
    def _source_errors(self):
        try:yield
        except ValueError as exc:
            raise Conflict('CPU original source unavailable or inconsistent') from exc

    def receipt(self,command_id):
        validate_schema(ID,command_id)
        with self._source_errors(),self.reader.snapshot() as (db,meta):
            read=ReadBudget(db,16*1024**2);value=read.object(self._stop_domain.SECTION,command_id)
            source=db.execute('SELECT event_type FROM events WHERE idempotency_key=?',(command_id,)).fetchone()
            if value is None and source is not None:
                from .hybrid_budget_ledger import EVENT as budget_event
                if (source[0]==self._stop_domain.EVENT or source[0]!=budget_event or
                        read.object(BUDGET[0],self._source_key(command_id)) is None):
                    raise Conflict('CPU command original projection/source missing or differs')
            if value is not None:
                self._stop_domain.validate_record(command_id,value)
                original=self.reader._point(db,read,value['registration_key'],meta['as_of_state_version'])
                self._stop_domain.validate_links(value,lambda s,k:original if (s,k)==(BUDGET[0],value['registration_key']) else None)
                if (any(value['request'][k]!=meta[k] for k in ('project_id','data_mode','store_epoch')) or
                        value['accepted_state_version']>meta['as_of_state_version'] or
                        getattr(self.store,self._store_proof)(db,command_id,_read=read)!=
                        ((self._stop_domain.EVENT,'hybrid-core',digest(value),value['accepted_state_version']),[(self._stop_domain.SECTION,command_id,digest(value))])):
                    raise Conflict('CPU stop intent whole original source differs')
                request=value['request']
                return {'schema_version':'1.1','command_id':command_id,'action':request['action'],'status':'ACCEPTED',
                    'accepted_state_version':value['accepted_state_version'],'request_hash':value['request_hash'],
                    'actor_id':request['actor_id'],'task_id':request['task_id'],'recorded_phase':'STOP_INTENT_ACCEPTED',
                    'execution_status':'UNKNOWN','native_execution_enabled':False,'arbitrary_tree_stop':False,'duplicate':False}
        with self._source_errors():return super().receipt(command_id)

    def check_stop_guard(self,db,guard):
        self._pure()
        if (type(guard) is not _StopGuard or guard.service is not self or guard.db is not db or
                guard.read.db is not db or guard.thread!=threading.get_ident() or not db.in_transaction or
                self._stop_guards.get(id(guard)) is not guard):
            raise PermissionError('actual issued CPU stop writer guard required')
        value=json.loads(guard.raw);access=self.auth.check_operator_guard(guard.auth_guard,project_id=self.project_id)
        if (value['request']['actor_id']!=access.principal.id or value['request']['task_id']!=self.task_id or
                value['registration_key']!=entry_key(self._registration['request']) or
                value['registration_hash']!=digest(self._registration) or not self.unit._cancelled.is_set()):
            raise PermissionError('actual human stop original scope and latch required')

    def check_stop_write(self,db,payload,inputs,guard):
        guard.check();value=json.loads(guard.raw)
        registration=self.reader._point(db,guard.read,value['registration_key'],value['acceptance_expected_state_version'])
        if canonical(registration)!=canonical(self._registration):
            raise Conflict('CPU stop original whole registration changed')
        if ([(s,k,v) for s,k,v in payload['put'] if k]!=[(self._stop_domain.SECTION,self._stop_domain.fact_key(value['request']),value)] or
                inputs!=self._stop_domain.event_inputs(value) or db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]!=
                value['acceptance_expected_state_version']):
            raise Conflict('CPU stop exact accepting mutation required')

    def _accept_stop(self,command,token,csrf):
        key=command['command_id']
        with self.store.lock(),self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');read=ReadBudget(db,16*1024**2)
            with self.auth.operator_guard(token,project_id=self.project_id,csrf=csrf) as auth_guard:
                if self.auth.check_operator_guard(auth_guard,project_id=self.project_id).principal.id!=command['actor_id']:
                    raise PermissionError('actual STOP actor changed')
                existing=self.receipt(key)
                if existing is not None:
                    if existing['request_hash']!=command['request_hash']:raise Conflict('command idempotency differs')
                    return {**existing,'duplicate':True}
                version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
                value=self._pending_stops.get(key)
                if value is None:
                    request={name:command[name] for name in ('action','task_id','actor_id','idempotency_key')}
                    request.update(project_id=self.project_id,data_mode='fixture',store_epoch=self.store_epoch)
                    now,_=self.runtime.controller._sample()
                    value=dict(schema_version='1.0',request=request,request_hash=command['request_hash'],
                        registration_key=entry_key(self._registration['request']),registration_hash=digest(self._registration),
                        acceptance_expected_state_version=version,accepted_state_version=version+1,recorded_at=now.isoformat())
                    self._pending_stops[key]=value
                if value['acceptance_expected_state_version']!=version:
                    raise Conflict('original unknown STOP acceptance CAS changed')
                guard=_StopGuard(self,db,read,auth_guard,value);self._stop_guards[id(guard)]=guard
                commit_entered=False
                try:
                    payload={'format':2,'put':([[self._stop_domain.SECTION,'',{}]] if guard.lookup(self._stop_domain.SECTION,'') is None else [])+
                        [[self._stop_domain.SECTION,key,value]],'delete':[],'details':None}
                    self.store._commit(db,self._stop_domain.EVENT,key,payload,version,digest(value),'hybrid-core',self._stop_domain.event_inputs(value),_authorization=guard)
                    guard.check();commit_entered=True;db.commit()
                except BaseException:
                    if not commit_entered:
                        db.rollback()  # Confirmed pre-COMMIT rollback permits a fresh internal acceptance CAS.
                        self._pending_stops.pop(key,None)
                    raise
                finally:self._stop_guards.pop(id(guard),None)
        return self.receipt(key)

    def prepare(self,body,*,token,csrf,origin,idempotency_key):
        # HTTP does this BEFORE waiting for a worker pool. No Pool/Store/source
        # locks or IO precede the accepted emergency memory latch.
        self._pure();check_bytes(body,4096);body=json.loads(canonical(body))
        if type(body) is not dict:raise ValueError('closed CPU command object required')
        validate_schema(self._stop_domain.BODY if body.get('action')==self._stop_action else self._start_body,body)
        if body['action'] not in (self._start_action,self._stop_action):
            raise Conflict('fixed CPU trial action required')
        validate_schema(ID,idempotency_key)
        if origin!=self.origin:raise PermissionError('same-origin CPU command required')
        with self.auth.operator_guard(token,project_id=self.project_id,csrf=csrf) as guard:
            access=self.auth.check_operator_guard(guard,project_id=self.project_id)
            if body['task_id']!=self.task_id:raise PermissionError('original CPU Task target required')
            key=control_command_id({'project_id':self.project_id,'data_mode':'fixture','store_epoch':self.store_epoch},
                                   access.principal.id,idempotency_key)
            command={**body,'actor_id':access.principal.id,'idempotency_key':idempotency_key,
                     'command_id':key,'request_hash':digest(body)}
            with self._intent_lock:
                entry=self._intents.get(key)
                if entry is not None and (entry['hash'],entry['actor'],entry['task'])!=(command['request_hash'],access.principal.id,self.task_id):
                    raise Conflict('CPU command idempotency key reused')
                if body['action']==self._stop_action:self.unit._cancelled.set()
                if entry is None:
                    if len(self._intents)>=32:raise Conflict('finite CPU command capacity reached')
                    self._intents[key]={'hash':command['request_hash'],'actor':access.principal.id,
                        'task':self.task_id,'dispatch_entered':False}
                if len(self._issued)>=64:raise Conflict('finite prepared CPU command capacity reached')
                operation=_Operation(command,token,csrf,self.unit.lease,threading.get_ident())
                self._issued[id(operation)]=operation
                self._operation_raw[id(operation)]=canonical(command)
        return operation

    def discard_unsubmitted(self,operation):
        # Only the HTTP queue's explicit zero-submission error may use this.
        with self._intent_lock:
            self._issued.pop(id(operation),None);self._operation_raw.pop(id(operation),None)

    def execute_prepared(self,operation,*,_stop_details=False):
        self._pure()
        if (self._issued.get(id(operation)) is not operation or
                self._operation_raw.get(id(operation))!=canonical(operation.command)):
            raise PermissionError('actual prepared CPU control required')
        operation.thread=threading.get_ident()
        if self._operation() is not None:raise Conflict('nested CPU command refused')
        self._local.operation=operation;command=operation.command
        try:
            if type(_stop_details) is not bool or (_stop_details and command['action']!=self._stop_action):
                raise ValueError('original STOP details only')
            if command['action']==self._stop_action:
                receipt=self._accept_stop(command,operation.token,operation.csrf)
                operation.accepted=True
                if _stop_details:
                    cleanup=None;error=None
                    try:
                        cleanup=self.unit.cancel()
                        self._after_stop_cleanup()
                    except Exception as exc:error=type(exc).__name__
                    return {'receipt':receipt,'cleanup':cleanup,'post_cleanup_status':'UNKNOWN' if error else 'RETURNED',
                        'error_type':error}
                self.unit.cancel()  # Strong original scoped cleanup, never global shutdown.
                self._after_stop_cleanup()
                return receipt
            self._session(operation.token,operation.csrf)
            existing=self.receipt(command['command_id'])
            if existing is not None:
                if existing['request_hash']!=command['request_hash']:raise Conflict('CPU command idempotency differs')
                return {**existing,'duplicate':True}
            with self._intent_lock:
                entry=self._intents[command['command_id']]
                if entry['dispatch_entered'] or self._start_intent is not None:
                    raise Conflict('CPU command outcome UNKNOWN; no second dispatch')
                entry['dispatch_entered']=True;self._start_intent=command['command_id']
            try:
                self.host.run(self.unit.lease,self.runtime._leases[id(self.unit.lease)]['token'],
                    idempotency_key=command['command_id'],expected_state_version=command['expected_state_version'])
            except Exception:
                existing=self.receipt(command['command_id'])
                if existing is None:
                    attempt=self.runtime._leases[id(self.unit.lease)]
                    if (self.unit._request is None and 'HANDOFF_UNKNOWN' not in attempt['entries'] and
                            not attempt['spawn_entered']):
                        with self._intent_lock:
                            entry['dispatch_entered']=False;self._start_intent=None
                    raise
                return existing
            existing=self.receipt(command['command_id'])
            if existing is None:raise Conflict('CPU RUN original HANDOFF receipt missing')
            return existing
        finally:
            self._local.operation=None;self._issued.pop(id(operation),None);self._operation_raw.pop(id(operation),None)

    def _after_stop_cleanup(self):
        pass

    def execute(self,body,*,token,csrf,origin,idempotency_key):
        return self.execute_prepared(self.prepare(body,token=token,csrf=csrf,origin=origin,idempotency_key=idempotency_key))

    def profile(self):
        with self._source_errors():value=self.reader.task(self.reservation_id)
        if value is None:raise Conflict('original CPU task source unavailable')
        try:self._pure();available=True
        except PermissionError:available=False
        last=self.unit._last
        status=(last['status'] if last is not None and last.get('fact') is not None and last['fact']['accepted_state_version']<=value['as_of_state_version'] else None)
        return {**value,'control_api_installed':True,'original_owner_available':available,
            'profile':self._profile,'last_sdk_status':status,
            'cancel_requested':self.unit._cancelled.is_set(),'goal_completed':False,
            'independent_review_status':'NOT_PERFORMED'}


class CpuUnitControlService(_OriginalUnitControl):
    """Exact registered CPU profile; original persisted domain is unchanged."""


def _install_units(app,services,projects,auth,*,origin,max_jobs,service_type,path,start_action,stop_action,state_prefix):
    from pathlib import Path
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlPool,ControlError,body,error_response
    from .hybrid_protocol import ProtocolError
    services=dict(services)
    if len(services)>128:raise ValueError('too many CPU unit controls')
    for key,service in services.items():
        project=projects.get(key)
        if (type(service) is not service_type or project is None or service.auth is not auth or
                service.origin!=origin or (key,project.data_mode)!=(service.project_id,'fixture') or
                service.store.root!=Path(project.root).resolve(strict=True)):
            raise ValueError('original CPU unit startup control binding required')
        service._pure()
        with service.reader.snapshot():pass
    starts,stops=ControlPool(max_jobs),ControlPool(2)
    setattr(app.state,state_prefix+'_start_pool',starts);setattr(app.state,state_prefix+'_stop_pool',stops)
    original_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(current):
        async with original_lifespan(current):
            try:yield
            finally:await starts.close();await stops.close()
    app.router.lifespan_context=lifespan

    def authorize(request,project_id,*,write=False):
        # Parent-only history remains readable after owner closure. A fork
        # must fail before inherited Auth or executor locks, without IO.
        if project_id in services and os.getpid()!=services[project_id].runtime.process['pid']:
            raise PermissionError('original parent CPU control reads required')
        authorization=request.headers.get('authorization')
        if write and authorization:raise ControlError(403,'PERMISSION_DENIED','human session commands required')
        if authorization:
            prefix,_,token=authorization.partition(' ');access=auth.resolve(token,'bearer') if prefix=='Bearer' else None
        else:
            token=request.cookies.get('rlflow_session');access=auth.resolve(token,'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        if project_id not in services or not access.principal.allows(project_id):raise ControlError(404,'NOT_FOUND','project not found')
        if write and (access.principal.kind!='human' or not access.principal.allows(project_id,'operator')):
            raise ControlError(403,'PERMISSION_DENIED','scoped human operator required')
        return services[project_id],token

    def failure(exc):
        if isinstance(exc,ControlError):return error_response(exc)
        if isinstance(exc,PermissionError):return error_response(ControlError(403,'PERMISSION_DENIED','original scoped human control required'))
        if isinstance(exc,Conflict) and 'idempotency' in str(exc):
            return error_response(ControlError(409,'IDEMPOTENCY_CONFLICT','CPU command key conflict'))
        if isinstance(exc,Conflict) and 'stale' in str(exc):
            return error_response(ControlError(409,'VERSION_CONFLICT','CPU task writer version conflict'))
        if isinstance(exc,Conflict):return error_response(ControlError(503,'UNKNOWN_EXECUTION','CPU command outcome unavailable',True))
        if isinstance(exc,(ValueError,ProtocolError)):return error_response(ControlError(400,'VALIDATION_ERROR','closed CPU unit request required'))
        return error_response(ControlError(503,'UNKNOWN_EXECUTION','CPU command outcome unavailable',True))

    @app.get('/api/v1/projects/{project_id}/'+path)
    async def profile(request:Request,project_id:str):
        try:
            if request.query_params:raise ValueError('closed CPU unit query required')
            service,_=authorize(request,project_id)
            result=await starts.run(service.profile)
            authorize(request,project_id)
            return JSONResponse(result)
        except Exception as exc:return failure(exc)

    @app.get('/api/v1/projects/{project_id}/'+path+'/commands/{command_id}')
    async def receipt(request:Request,project_id:str,command_id:str):
        try:
            if request.query_params:raise ValueError('closed CPU receipt query required')
            service,_=authorize(request,project_id)
            result=await starts.run(lambda:service.receipt(command_id))
            authorize(request,project_id)
            if result is None:raise ControlError(404,'NOT_FOUND','command not found')
            return JSONResponse(result)
        except Exception as exc:return failure(exc)

    @app.post('/api/v1/projects/{project_id}/'+path+'/commands')
    async def commands(request:Request,project_id:str):
        try:
            if project_id in services:services[project_id]._pure()  # BEFORE inherited Auth/executor locks.
            if request.query_params:raise ValueError('closed CPU command query required')
            counts={}
            for key,value in request.scope['headers']:counts[key]=counts.get(key,0)+1
            if any(counts.get(k,0)>1 for k in (b'x-csrf-token',b'idempotency-key',b'content-type')):
                raise ControlError(403,'PERMISSION_DENIED','ambiguous command headers')
            if request.headers.get('origin')!=origin or not request.headers.get('x-csrf-token'):
                raise ControlError(403,'PERMISSION_DENIED','same-origin session CSRF required')
            payload=await body(request)
            service,token=authorize(request,project_id,write=True)
            operation=service.prepare(payload,token=token,csrf=request.headers['x-csrf-token'],origin=origin,
                                      idempotency_key=request.headers.get('idempotency-key'))
            pool=stops if operation.command['action']==stop_action else starts
            try:result=await pool.run(lambda:service.execute_prepared(operation))
            except ControlError:
                service.discard_unsubmitted(operation);raise
            return JSONResponse(result,status_code=202)
        except Exception as exc:return failure(exc)


def install(app,services,projects,auth,*,origin,max_jobs):
    return _install_units(app,services,projects,auth,origin=origin,max_jobs=max_jobs,
        service_type=CpuUnitControlService,path='cpu-unit',start_action='START_FIXED_CPU',
        stop_action='CANCEL_FIXED_CPU_TRIAL',state_prefix='cpu_unit')
