"""Private original finite-scope emergency STOP, never a global Goal STOP.

All original scopes are latched before any Store/Pool/producer work. Original
human STOP facts remain separate per-project facts; no cross-DB atomic receipt.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
import json
import os
import threading

from .hybrid_cpu_unit_control import CpuUnitControlService
from .hybrid_engineering_unit_control import EngineeringUnitControlService
from .hybrid_fixture_runtime_ledger import control_command_id
from .hybrid_goals import digest
from .hybrid_host_execution import HostExecutionService
from .hybrid_protocol import ID,validate_schema
from .store import Conflict,canonical
from .web_auth import AuthStore

ACTION='CANCEL_ORIGINAL_FINITE_UNITS'

@dataclass(frozen=True,eq=False)
class _Batch:
    id: str
    actor: str
    key: str
    token: str
    csrf: str
    commands: tuple

class FiniteHostStop:
    def __init__(self,host,controls,auth,*,origin):
        if type(host) is not HostExecutionService or type(auth) is not AuthStore:
            raise TypeError('original finite Host and Auth required')
        host._pure_identity()
        if type(controls) not in (tuple,list):raise ValueError('finite controls required')
        captured=tuple(controls[:4])
        if not 1<=len(captured)<=3:raise ValueError('one to three original controls required')
        projects=set();roots=set()
        for service in captured:
            if type(service) not in (CpuUnitControlService,EngineeringUnitControlService):
                raise TypeError('exact original control required')
            service._pure()
            if (service.host is not host or service.auth is not auth or service.origin!=origin or
                    service.runtime.pool is not host.pool or service.store._hybrid_auth_owner is not auth or
                    service.store is not service.runtime.store or
                    (service.project_id,service.store_epoch)!=(service.runtime.workspace.project_id,service.runtime.workspace.store_epoch) or
                    service.task_id!=service.runtime._leases[id(service.unit.lease)]['origin']['task_id'] or
                    service.project_id in projects or service.store.root in roots):
                raise ValueError('original finite STOP binding differs')
            projects.add(service.project_id);roots.add(service.store.root)
        captured=tuple(sorted(captured,key=lambda s:s.project_id))
        self.host,self.controls,self.auth,self.origin=host,captured,auth,origin
        self._auth=auth
        self._controls=captured
        self._signature=tuple((s.project_id,s.store_epoch,s.task_id,s._stop_action,s.store,s.unit) for s in captured)
        self._scope=digest([list(row[:4]) for row in self._signature])
        self._lock=threading.Lock();self._rows={};self._issued={};self._raw={}
        self._active=0;self._closed=False;self._safety={}
        self._cleanup_slots=threading.BoundedSemaphore(3)
        with host.pool._lock:
            host._pure_identity()
            if getattr(host,'_finite_host_stop',None) is not None:
                raise Conflict('one original finite STOP coordinator required')
            self._executor=ThreadPoolExecutor(max_workers=3,thread_name_prefix='finite-stop')
            host._finite_host_stop=self

    def _parent_identity(self):
        if os.getpid()!=self.host.pool.process['pid']:
            raise PermissionError('original finite STOP parent required')
        if getattr(self.host,'_finite_host_stop',None) is not self or self.controls is not self._controls:
            raise PermissionError('actual original finite STOP required')

    def _pure(self):
        self._parent_identity();self.host._pure_identity()
        if self.auth is not self._auth:raise PermissionError('original finite STOP Auth required')
        for s,row in zip(self.controls,self._signature):
            s._pure()
            if ((s.project_id,s.store_epoch,s.task_id,s._stop_action,s.store,s.unit)!=row or
                    s.host is not self.host or s.auth is not self.auth or s.store._hybrid_auth_owner is not self.auth or s.origin!=self.origin):
                raise PermissionError('original finite STOP scope changed')

    def _safety_cancel(self):
        # At most one retained fallback future per original Unit. Capacity
        # refusal cannot turn off the emergency latch or grow an unbounded
        # default executor queue. Only called AFTER whole-scope authorization.
        with self._lock:
            if self._closed:return
            for service in self.controls:
                if service not in self._safety:
                    self._safety[service]=self._executor.submit(self._safety_scope,service)

    def _safety_scope(self,service):
        with self._cleanup_slots:return service.unit.cancel()

    def prepare(self,body,*,token,csrf,origin,idempotency_key):
        self._pure()
        if type(body) is not dict or len(body)!=1 or type(body.get('action')) is not str or body.get('action')!=ACTION:
            raise ValueError('closed original finite STOP action required')
        validate_schema(ID,idempotency_key)
        if origin!=self.origin:raise PermissionError('same-origin finite STOP required')
        first=self.controls[0];capacity=False
        with self.auth.operator_guard(token,project_id=first.project_id,csrf=csrf) as guard:
            access=self.auth.check_operator_guard(guard,project_id=first.project_id)
            if any(not access.principal.allows(s.project_id,'operator') for s in self.controls):
                raise PermissionError('human operator required for every original finite scope')
            commands=[]
            for s in self.controls:
                child={'action':s._stop_action,'task_id':s.task_id}
                key=control_command_id({'project_id':s.project_id,'data_mode':'fixture','store_epoch':s.store_epoch},
                    access.principal.id,idempotency_key)
                commands.append((s,child,key,digest(child)))
            with ExitStack() as locks:
                for s in self.controls:locks.enter_context(s._intent_lock)
                locks.enter_context(self._lock)
                self._pure()
                if self._closed:raise Conflict('original finite STOP coordinator closed')
                for s,child,key,request_hash in commands:
                    entry=s._intents.get(key)
                    if entry is not None and (entry['hash'],entry['actor'],entry['task'])!=(request_hash,access.principal.id,s.task_id):
                        raise Conflict('finite STOP original command idempotency key reused')
                self.auth.check_operator_guard(guard,project_id=first.project_id)
                for s in self.controls:s.unit._cancelled.set()
                # These reserves contain the EXACT existing per-project STOP
                # hash/actor/Task; each actual write reauthenticates in its own
                # issued original project guard, outside these memory locks.
                for s,child,key,request_hash in commands:
                    if key not in s._intents and len(s._intents)<32:
                        s._intents[key]={'hash':request_hash,'actor':access.principal.id,
                            'task':s.task_id,'dispatch_entered':False}
                identity=(access.principal.id,idempotency_key)
                row=self._rows.get(identity)
                if row is not None:
                    batch=row['operation']
                    if not row['running']:
                        self._issued.pop(id(batch),None);self._raw.pop(id(batch),None)
                        batch=_Batch(batch.id,batch.actor,batch.key,token,csrf,tuple(commands))
                        row['operation']=batch;self._issued[id(batch)]=batch
                        self._raw[id(batch)]=canonical([batch.id,batch.actor,batch.key,digest([token,csrf]),
                            [[s.project_id,child,key,h] for s,child,key,h in commands]])
                    return batch
                if len(self._rows)>=32:
                    capacity=True
                else:
                    batch=_Batch('finite_stop_'+digest([self._scope,*identity]).removeprefix('sha256:'),
                        access.principal.id,idempotency_key,token,csrf,tuple(commands))
                    self._issued[id(batch)]=batch
                    self._raw[id(batch)]=canonical([batch.id,batch.actor,batch.key,digest([token,csrf]),
                        [[s.project_id,child,key,h] for s,child,key,h in commands]])
                    self._rows[identity]={'operation':batch,'running':False,'result':None}
        if capacity:
            self._safety_cancel()
            raise Conflict('finite STOP capacity refused; all original cancels latched')
        return batch

    def _scope_stop(self,service,body,batch):
        with self._cleanup_slots:return self._scope_stop_held(service,body,batch)

    @staticmethod
    def _scope_stop_held(service,body,batch):
        receipt=None;cleanup=None;error=None;operation=None;post='UNKNOWN'
        try:
            operation=service.prepare(body,token=batch.token,csrf=batch.csrf,
                origin=service.origin,idempotency_key=batch.key)
            result=service.execute_prepared(operation,_stop_details=True)
            receipt,cleanup=result['receipt'],result['cleanup']
            post,error=result['post_cleanup_status'],result['error_type']
        except Exception as exc:
            # Only original scoped cap cleanup, no renewed Auth/Controller,
            # candidate write, machine acceptance or new worker effects.
            error=type(exc).__name__
            if operation is not None and getattr(operation,'_accept_cleanup_attempted',False):
                cleanup=operation._accept_cleanup_result
            else:
                try:cleanup=service.unit.cancel()
                except Exception:cleanup=None
        return {'project_id':service.project_id,'store_epoch':service.store_epoch,'task_id':service.task_id,
            'intent':receipt,'intent_status':'ACCEPTED' if receipt is not None else 'UNKNOWN',
            'cleanup_status':'ORIGINAL_SCOPE_STOPPED' if cleanup is not None and cleanup['status']=='CANCELLED_SCOPE_STOPPED' else 'UNKNOWN',
            'post_cleanup_status':post,
            'error_type':error,'goal_completed':False,'independent_review_status':'NOT_PERFORMED'}

    def execute_prepared(self,batch,*,_resume_unknown=False):
        self._pure()
        if (type(batch) is not _Batch or self._issued.get(id(batch)) is not batch or
                len(batch.commands)!=len(self.controls) or
                any(command[0] is not service for command,service in zip(batch.commands,self.controls)) or
                self._raw.get(id(batch))!=canonical([batch.id,batch.actor,batch.key,digest([batch.token,batch.csrf]),
                    [[s.project_id,child,key,h] for s,child,key,h in batch.commands]])):
            raise PermissionError('actual original prepared finite STOP required')
        row=self._rows[(batch.actor,batch.key)]
        if type(_resume_unknown) is not bool:raise ValueError('actual resume flag required')
        with self._lock:
            previous=None if row['result'] is None else json.loads(row['result'])
            if previous is not None and (not _resume_unknown or previous['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'):
                return {**previous,'duplicate':True}
            if row['running']:raise Conflict('original finite STOP is still running; no duplicate cleanup')
            if self._closed or self._active>=2:capacity=True
            else:
                capacity=False;self._active+=1;row['running']=True
        if capacity:
            self._safety_cancel()
            raise Conflict('finite STOP queue capacity refused; all original cancels latched')
        submitted=[];items=[None]*len(batch.commands) if previous is None else previous['items'];stored=[False]
        try:
            # Submit ALL finite scopes before waiting for any project.
            fallback={}
            for index,(s,body,_,_) in enumerate(batch.commands):
                if previous is not None and previous['items'][index]['intent_status']=='ACCEPTED' and previous['items'][index]['cleanup_status']=='ORIGINAL_SCOPE_STOPPED' and previous['items'][index]['post_cleanup_status']=='RETURNED':
                    items[index]=previous['items'][index];continue
                try:submitted.append((index,self._executor.submit(self._scope_stop,s,body,batch)))
                except Exception:fallback[index]=(s,body)
            # Even partial submission cannot free capacity/mark non-running
            # while original futures still run. All other scopes were offered
            # their independent workers BEFORE any blocking fallback/wait.
            for index,(s,body) in fallback.items():
                try:items[index]=self._scope_stop(s,body,batch)
                except Exception:items[index]=self._unknown(index)
            for index,future in submitted:
                try:items[index]=future.result()
                except Exception:items[index]=self._unknown(index)
            complete=all(r['intent_status']=='ACCEPTED' and r['cleanup_status']=='ORIGINAL_SCOPE_STOPPED' and r['post_cleanup_status']=='RETURNED' for r in items)
            result={'schema_version':'1.1','command_id':batch.id,'action':ACTION,'duplicate':False,
                'status':'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN' if complete else 'PARTIAL_OR_UNKNOWN',
                'scope':'ORIGINAL_FIXED_BOUND_UNITS_ONLY','durable_aggregate_receipt':False,
                'cleanup_resume':_resume_unknown,
                'items':items,'goal_completed':False,'independent_review_status':'NOT_PERFORMED'}
            with self._lock:row['result']=canonical(result);stored[0]=True
            return json.loads(row['result'])
        finally:
            # A cancelled/interrupted SDK waiter does not own worker lifetime.
            # Keep capacity/running until EVERY actually submitted future is
            # terminal; callbacks also preserve results after a lost waiter.
            pending={future for _,future in submitted};released=[False]
            def finalized(future=None):
                with self._lock:
                    pending.discard(future)
                    if pending or released[0]:return
                    released[0]=True
                    if not stored[0]:
                        for index,job in submitted:
                            try:items[index]=job.result()
                            except BaseException:items[index]=self._unknown(index)
                        saved=[item if item is not None else self._unknown(i) for i,item in enumerate(items)]
                        complete=all(r['intent_status']=='ACCEPTED' and r['cleanup_status']=='ORIGINAL_SCOPE_STOPPED' and r['post_cleanup_status']=='RETURNED' for r in saved)
                        row['result']=canonical({'schema_version':'1.1','command_id':batch.id,'action':ACTION,
                            'duplicate':False,'status':'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN' if complete else 'PARTIAL_OR_UNKNOWN','scope':'ORIGINAL_FIXED_BOUND_UNITS_ONLY',
                            'durable_aggregate_receipt':False,'cleanup_resume':_resume_unknown,'items':saved,
                            'goal_completed':False,'independent_review_status':'NOT_PERFORMED'})
                    self._active-=1;row['running']=False
            if not pending:finalized()
            else:
                for _,job in submitted:job.add_done_callback(finalized)

    def _unknown(self,index):
        project,epoch,task,*_=self._signature[index]
        return {'project_id':project,'store_epoch':epoch,'task_id':task,'intent':None,'intent_status':'UNKNOWN',
            'cleanup_status':'UNKNOWN','post_cleanup_status':'UNKNOWN','error_type':'ScopeFailure',
            'goal_completed':False,'independent_review_status':'NOT_PERFORMED'}

    def read_result(self,command_id,*,actor_id):
        """Original as-of-return cleanup, with fresh immutable intent proofs.

        No new STOP, cleanup, resampling or cold owner reconstruction. Each
        project source is checked separately: never a distributed snapshot.
        """
        self._pure()  # Parent/original identity before any inherited lock.
        validate_schema(ID,command_id);validate_schema(ID,actor_id)
        with self._lock:
            row=next((r for (actor,_),r in self._rows.items()
                      if actor==actor_id and r['operation'].id==command_id),None)
            if row is None or row['result'] is None:return None
            raw=row['result'];batch=row['operation']
            batch_id,batch_actor,batch_key=batch.id,batch.actor,batch.key
            credential_hash=digest([batch.token,batch.csrf])
            commands=tuple((s,json.loads(canonical(body)),key,h) for s,body,key,h in batch.commands)
            if (type(batch) is not _Batch or self._issued.get(id(batch)) is not batch or
                    batch_actor!=actor_id or len(commands)!=len(self.controls) or
                    any(command[0] is not service for command,service in zip(commands,self.controls)) or
                    self._raw.get(id(batch))!=canonical([batch_id,batch_actor,batch_key,credential_hash,
                        [[s.project_id,child,key,h] for s,child,key,h in commands]])):
                raise PermissionError('actual original immutable finite STOP required')
            for service,body,key,request_hash in commands:
                if (body!={'action':service._stop_action,'task_id':service.task_id} or
                        request_hash!=digest(body) or key!=control_command_id(
                            {'project_id':service.project_id,'data_mode':'fixture','store_epoch':service.store_epoch},
                            batch_actor,batch_key)):
                    raise PermissionError('original finite STOP command scope required')
        result=json.loads(raw)
        if (result['command_id']!=batch_id or len(result['items'])!=len(commands)):
            raise Conflict('original finite STOP cached scope differs')
        for item,(service,body,key,request_hash) in zip(result['items'],commands):
            if (item['project_id'],item['store_epoch'],item['task_id'])!=(service.project_id,service.store_epoch,service.task_id):
                raise Conflict('original finite STOP cached item scope differs')
            receipt=service.receipt(key)
            if receipt is not None and (receipt['action'],receipt['request_hash'],receipt['actor_id'],receipt['task_id'])!=\
                    (body['action'],request_hash,batch_actor,service.task_id):
                raise Conflict('original finite STOP command source differs')
            if item['intent'] is None:
                if item['intent_status']!='UNKNOWN':
                    raise Conflict('original finite STOP intent status differs')
                continue  # No promotion of unknown acceptance from history.
            if (receipt is None or receipt!=item['intent'] or
                    (receipt['action'],receipt['request_hash'],receipt['actor_id'],receipt['task_id'])!=
                    (body['action'],request_hash,batch_actor,service.task_id) or
                    item['intent_status']!='ACCEPTED'):
                raise Conflict('original finite STOP accepted source differs')
        self._pure()
        return {**result,'duplicate':True}

    def close(self):
        self._parent_identity()
        with self._lock:self._closed=True
        self._executor.shutdown(wait=True,cancel_futures=False)


def install(app,coordinator):
    """Private opt-in HTTP transport of the original finite capture only."""
    import asyncio
    from contextlib import asynccontextmanager
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlPool,ControlError,body,error_response
    from .hybrid_protocol import ProtocolError
    coordinator._pure()
    jobs=ControlPool(2)
    disk_jobs=ControlPool(1)
    read_jobs=ControlPool(2)
    app.state.finite_host_stop=coordinator
    app.state.finite_host_stop_pool=jobs
    app.state.finite_host_disk_pool=disk_jobs
    app.state.finite_host_receipt_pool=read_jobs
    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(current):
        async with original(current):
            try:yield
            finally:
                drain=getattr(current.state,'agent_request_stop_drain',None)
                if drain is not None:await drain()
                await jobs.close()
                await disk_jobs.close()
                await read_jobs.close()
                await asyncio.to_thread(coordinator.close)
    app.router.lifespan_context=lifespan

    def authorize(request,*,write=False):
        coordinator._parent_identity()  # BEFORE inherited Auth/worker locks.
        authorization=request.headers.get('authorization')
        if write and authorization:raise ControlError(403,'PERMISSION_DENIED','human session required')
        if authorization:
            prefix,_,token=authorization.partition(' ')
            access=coordinator.auth.resolve(token,'bearer') if prefix=='Bearer' else None
        else:
            token=request.cookies.get('rlflow_session')
            access=coordinator.auth.resolve(token,'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        if any(not access.principal.allows(row[0]) for row in coordinator._signature):
            raise ControlError(404,'NOT_FOUND','original finite scope unavailable')
        if write and (access.principal.kind!='human' or any(not access.principal.allows(row[0],'operator') for row in coordinator._signature)):
            raise ControlError(403,'PERMISSION_DENIED','whole original scoped human operator required')
        return token,access

    def failure(exc):
        if isinstance(exc,ControlError):return error_response(exc)
        if isinstance(exc,PermissionError):return error_response(ControlError(403,'PERMISSION_DENIED','original finite scope permission required'))
        if isinstance(exc,(ValueError,ProtocolError)):return error_response(ControlError(400,'VALIDATION_ERROR','closed finite STOP request required'))
        if isinstance(exc,Conflict) and 'idempotency' in str(exc):return error_response(ControlError(409,'IDEMPOTENCY_CONFLICT','original finite STOP key conflict'))
        return error_response(ControlError(503,'UNKNOWN_EXECUTION','original finite STOP outcome unavailable',True))

    @app.get('/api/v1/finite-host')
    async def profile(request:Request):
        try:
            if request.query_params:raise ValueError('closed original scope query required')
            _,access=authorize(request)
            try:coordinator._pure();available=not coordinator._closed
            except PermissionError:available=False
            return JSONResponse({'schema_version':'1.1','profile':'ORIGINAL_FIXED_BOUND_UNITS_ONLY',
                'scope_sha256':coordinator._scope,'data_mode':'fixture','execution_enabled':False,
                'original_owner_available':available,
                'stop_enabled':available and access.method=='session' and access.principal.kind=='human' and
                    all(access.principal.allows(row[0],'operator') for row in coordinator._signature),
                'items':[{'project_id':r[0],'store_epoch':r[1],'task_id':r[2],'stop_action':r[3]} for r in coordinator._signature],
                'goal_completed':False,'independent_review_status':'NOT_PERFORMED'})
        except Exception as exc:return failure(exc)

    @app.get('/api/v1/finite-host/disk-admission')
    async def disk_admission(request:Request):
        try:
            if request.query_params:raise ValueError('closed original scope query required')
            authorize(request)
            coordinator._pure()
            # Explicit current diagnostic, not cached telemetry or authority.
            value=await disk_jobs.run(coordinator.host._disk.health)
            authorize(request)
            coordinator._pure()
            return JSONResponse(value)
        except Conflict:
            return error_response(ControlError(503,'UNKNOWN_EXECUTION','original disk observation unavailable',True))
        except Exception as exc:return failure(exc)

    @app.get('/api/v1/finite-host/commands/{command_id}')
    async def receipt(request:Request,command_id:str):
        try:
            if request.query_params:raise ValueError('closed finite receipt query required')
            _,access=authorize(request);validate_schema(ID,command_id)
            result=await read_jobs.run(lambda:coordinator.read_result(command_id,actor_id=access.principal.id))
            if result is None:raise ControlError(404,'NOT_FOUND','original finite result unavailable')
            authorize(request)
            return JSONResponse(result)
        except Conflict:
            # Conflict is a ValueError subclass; source damage is UNKNOWN,
            # not a malformed caller request through failure(...).
            return error_response(ControlError(503,'UNKNOWN_EXECUTION','original finite STOP source unavailable',True))
        except Exception as exc:return failure(exc)

    @app.post('/api/v1/finite-host/commands')
    async def commands(request:Request):
        try:
            coordinator._pure()
            if (set(request.query_params)-{'resume_cleanup'} or
                    ('resume_cleanup' in request.query_params and request.query_params.getlist('resume_cleanup')!=['1'])):
                raise ValueError('explicit original unknown cleanup resume only')
            counts={}
            for key,_ in request.scope['headers']:counts[key]=counts.get(key,0)+1
            if any(counts.get(key,0)>1 for key in (b'origin',b'cookie',b'authorization',b'x-csrf-token',b'idempotency-key',b'content-type')):
                raise ControlError(403,'PERMISSION_DENIED','ambiguous finite command headers')
            if request.headers.get('origin')!=coordinator.origin or not request.headers.get('x-csrf-token'):
                raise ControlError(403,'PERMISSION_DENIED','same-origin session CSRF required')
            payload=await body(request);token,_=authorize(request,write=True)
            batch=coordinator.prepare(payload,token=token,csrf=request.headers['x-csrf-token'],
                origin=coordinator.origin,idempotency_key=request.headers.get('idempotency-key'))
            try:
                result=await jobs.run(lambda:coordinator.execute_prepared(batch,
                    _resume_unknown='resume_cleanup' in request.query_params))
            except ControlError:
                # Explicit HTTP zero-submission refusal occurs AFTER the
                # authenticated whole-scope latch. Do not abandon original
                # cap cleanup or fabricate a durable STOP acceptance.
                coordinator._safety_cancel()
                raise
            authorize(request)
            return JSONResponse(result,status_code=202 if result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN' else 200)
        except Exception as exc:return failure(exc)
