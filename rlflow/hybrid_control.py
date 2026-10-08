"""Explicit opt-in non-executing HTTP controls over protected core services.

No config/credential/path upload, legacy control fallback, scheduler or lease.
Only a trusted host can inject the actual fixed service instances at startup.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import secrets
import threading

from fastapi import Request
from fastapi.responses import JSONResponse

from .hybrid_authority import ApprovalService, SECTIONS as AUTHORITY, validate_record as authority_record
from .hybrid_drafts import DraftService
from .hybrid_goals import SECTIONS as DRAFTS, control_command_key, digest, validate_record as draft_record
from .hybrid_protocol import ID, COUNT, obj, validate, validate_schema, ProtocolError
from .store import Conflict

COOKIE='rlflow_session'


@dataclass(frozen=True)
class ControlServices:
    drafts: DraftService
    approvals: ApprovalService


class ControlError(Exception):
    def __init__(self,status,code,message,retryable=False,details=None):
        self.status,self.code,self.message,self.retryable,self.details=status,code,message,retryable,details or {}


class ControlPool:
    """Capacity follows the actual finite worker future, never the HTTP waiter."""
    def __init__(self,limit):
        if type(limit) is not int or not 1<=limit<=8:raise ValueError('invalid control capacity')
        self.limit,self.pending,self.closed=limit,0,False
        self.lock=threading.Lock();self.executor=ThreadPoolExecutor(max_workers=min(2,limit),thread_name_prefix='hybrid-control')

    async def run(self,call):
        with self.lock:
            if self.closed:raise ControlError(503,'UNSUPPORTED_CAPABILITY','control service closed')
            if self.pending>=self.limit:raise ControlError(429,'BUDGET_EXHAUSTED','control capacity reached',True)
            self.pending+=1
            try:future=self.executor.submit(call)
            except BaseException:
                self.pending-=1
                raise
        def release(_):
            with self.lock:self.pending-=1
        future.add_done_callback(release)
        wrapped=asyncio.wrap_future(future)
        # Retrieve an eventual exception even if the disconnected waiter is gone.
        wrapped.add_done_callback(lambda f:None if f.cancelled() else f.exception())
        return await asyncio.shield(wrapped)

    async def close(self):
        with self.lock:self.closed=True
        await asyncio.to_thread(self.executor.shutdown,wait=True,cancel_futures=False)


def error_response(error):
    return JSONResponse({'code':error.code,'message':error.message,'retryable':error.retryable,
        'correlation_id':'control_error_'+secrets.token_hex(12),'details':error.details},status_code=error.status)


async def body(request):
    if request.headers.get('content-type','').split(';',1)[0]!='application/json':
        raise ControlError(400,'VALIDATION_ERROR','JSON body required')
    chunks=[];size=0
    try:
        async with asyncio.timeout(3):
            async for chunk in request.stream():
                size+=len(chunk)
                if size>256*1024:raise ControlError(413,'VALIDATION_ERROR','control payload too large')
                chunks.append(chunk)
    except TimeoutError:raise ControlError(408,'VALIDATION_ERROR','control payload timeout') from None
    raw=b''.join(chunks)
    if 1+sum(raw.count(c) for c in (b'{',b'[',b',',b':'))>256*1024:
        raise ControlError(413,'VALIDATION_ERROR','control structure too large')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('duplicate key')
            value[key]=item
        return value
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (ValueError,UnicodeError,RecursionError):raise ControlError(400,'VALIDATION_ERROR','invalid closed JSON payload') from None


def command_dto(command_id,receipt,*,duplicate=False):
    request=receipt['request'];action=request['action']
    if action=='propose_goal_draft':
        result={'goal_id':request['proposal']['goal_id'],'state':'DRAFT','proposal_hash':receipt['contract_hash'],
                'contract_version':request['proposal']['contract_version'],'execution_enabled':False}
        action='submit_goal'
    else:
        result={'goal_id':request['confirmation']['goal_id'] if action=='approve' else request['goal_id'],
                'fact_key':receipt['fact_key'],'state':'LEASE_VALIDATION_PENDING' if action=='approve' else 'REVOKED',
                'execution_enabled':False}
    result['as_of_state_version']=receipt['accepted_state_version']
    return {'schema_version':'1.1','command_id':command_id,'action':action,'status':'SUCCEEDED',
            'accepted_state_version':receipt['accepted_state_version'],'duplicate':duplicate,'result':result}


def read_receipt(store,command_id):
    """Bounded consistent receipt + source read; never return the raw witness."""
    with store.connect() as db:
        # Every legal JSON parse's conservative structural count is <= its
        # raw bytes. Cover the existing legal catalog/request byte envelope,
        # including literal-marker encoding expansion and source/blob rereads.
        # A minimal literal dict becomes a hash+literal descriptor (~6x); the
        # 256KiB catalog plus bounded request/source fit this finite envelope.
        db.execute('BEGIN');budget=[4*1024*1024];nodes=[4*1024*1024]
        def parse(raw):
            budget[0]-=len(raw);nodes[0]-=1+sum(raw.count(c) for c in (b'{',b'[',b',',b':'))
            if budget[0]<0 or nodes[0]<0:raise Conflict('control read exceeds budget')
            return json.loads(raw)
        def decode(value):
            if isinstance(value,dict) and set(value) in ({'$rlflow_blob'},{'$rlflow_blob','literal'}):
                row=db.execute('SELECT data FROM blobs WHERE digest=? AND length(data)<=?',(value['$rlflow_blob'],budget[0])).fetchone()
                if row is None or hashlib.sha256(row[0]).hexdigest()!=value['$rlflow_blob']:raise Conflict('control blob missing or corrupt')
                literal=value.get('literal',False);value=parse(row[0])
                if literal:return value
            if isinstance(value,dict):return {k:decode(v) for k,v in value.items()}
            if isinstance(value,list):return [decode(v) for v in value]
            return value
        found=None
        for section,validator in ((DRAFTS[2],draft_record),(AUTHORITY[3],authority_record)):
            row=db.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=? THEN value END AS value FROM projection WHERE section=? AND object_key=?',
                (budget[0],section,command_id)).fetchone()
            if row is None:continue
            if row['value'] is None or found is not None:raise Conflict('invalid control receipt source')
            receipt=decode(parse(row['value'].encode()));validator(section,command_id,receipt)
            r=receipt['request']
            if r.get('control_command_id')!=command_id:raise ControlError(404,'NOT_FOUND','command not found')
            if store._goal_registration(db)!=(r['project_id'],r['data_mode']):raise Conflict('control receipt registration mismatch')
            event=store._goal_event(db,command_id)
            expected_type='HYBRID_GOAL_DRAFTED' if section==DRAFTS[2] else ('HYBRID_GOAL_APPROVED' if r['action']=='approve' else 'HYBRID_APPROVAL_REVOKED')
            if event!=(expected_type,'hybrid-core',receipt['request_hash'],receipt['accepted_state_version']):raise Conflict('control receipt original source mismatch')
            if section==AUTHORITY[3]:
                source=store._authority_event(db,command_id,max_bytes=min(budget[0],3*1024*1024),_parse=parse,_decode=decode)
                if source is None or (section,command_id,digest(receipt)) not in source[1]:raise Conflict('control receipt original payload mismatch')
            found=receipt
        if found is None:raise ControlError(404,'NOT_FOUND','command not found')
        return found


def install(app,services,projects,auth,*,origin,max_jobs):
    from .hybrid_reads import HybridReader
    services=dict(services)
    if len(services)>128:raise ValueError('too many control services')
    for project_id,pair in services.items():
        project=projects.get(project_id)
        if type(pair) is not ControlServices or type(pair.drafts) is not DraftService or type(pair.approvals) is not ApprovalService:
            raise ValueError('actual protected control services required')
        draft,approval=pair.drafts,pair.approvals
        try:project_root=Path(project.root).resolve(strict=True) if project is not None else None
        except OSError:raise ValueError('control project root unavailable') from None
        if (project is None or draft.store is not approval.store or draft.auth is not auth or approval.auth is not auth
                or draft.origin!=origin or approval.origin!=origin or (draft.project_id,draft.data_mode)!=(project.id,project.data_mode)
                or (approval.project_id,approval.data_mode)!=(project.id,project.data_mode) or draft.store.root!=project_root
                or draft.store._hybrid_draft_service is not draft or draft.store._hybrid_authority_service is not approval
                or draft.store._hybrid_draft_auth_owner is not auth or draft.store._hybrid_auth_owner is not auth
                or draft.store._hybrid_registry is not approval.registry):
            raise ValueError('control service binding mismatch')
    pool=ControlPool(max_jobs);app.state.hybrid_control_pool=pool
    readers={key:HybridReader(pair.drafts.store,project_id=key,data_mode=pair.drafts.data_mode,
                             store_epoch=pair.drafts.store_epoch,clock=pair.approvals.clock) for key,pair in services.items()}
    original_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(current):
        async with original_lifespan(current):
            try:yield
            finally:await pool.close()
    app.router.lifespan_context=lifespan

    def authorize(request,project_id,role=None):
        authorization=request.headers.get('authorization')
        if authorization and role:raise ControlError(403,'PERMISSION_DENIED','human session controls required')
        if authorization:
            prefix,_,token=authorization.partition(' ')
            access=auth.resolve(token,'bearer') if prefix=='Bearer' else None
        else:
            token=request.cookies.get(COOKIE);access=auth.resolve(token,'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        if project_id not in services or not access.principal.allows(project_id):raise ControlError(404,'NOT_FOUND','project not found')
        allowed=any(access.principal.allows(project_id,r) for r in ('operator','approver')) if role=='review' else access.principal.allows(project_id,role) if role else True
        if role and (access.principal.kind!='human' or not allowed):
            raise ControlError(403,'PERMISSION_DENIED','scoped role required')
        return token,access,services[project_id]

    def boundary(request,*,idempotency=False):
        counts={}
        for key,value in request.scope['headers']:counts[key]=counts.get(key,0)+1
        if any(counts.get(k,0)>1 for k in (b'x-csrf-token',b'idempotency-key',b'content-type')):
            raise ControlError(403,'PERMISSION_DENIED','ambiguous control headers')
        if request.headers.get('origin')!=origin or not request.headers.get('x-csrf-token'):
            raise ControlError(403,'PERMISSION_DENIED','same-origin session CSRF required')
        if idempotency:
            try:validate_schema(ID,request.headers.get('idempotency-key'))
            except ProtocolError:raise ControlError(400,'VALIDATION_ERROR','valid Idempotency-Key required') from None

    async def response(call,*,status=200,request=None,project_id=None):
        try:return JSONResponse(await pool.run(call),status_code=status)
        except ControlError as error:return error_response(error)
        except PermissionError:return error_response(ControlError(403,'PERMISSION_DENIED','live scoped session required'))
        except ProtocolError as error:
            code=error.code if error.code in ('UNSUPPORTED_CAPABILITY','PERMISSION_DENIED') else 'VALIDATION_ERROR'
            return error_response(ControlError(403 if code=='PERMISSION_DENIED' else 400,code,'control request rejected'))
        except Conflict as error:
            if 'idempotency' in str(error):return error_response(ControlError(409,'IDEMPOTENCY_CONFLICT','command key conflict'))
            if not any(word in str(error) for word in ('stale','epoch changed','confirmation epoch or registry changed','not current draft revision')):
                return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','control source unavailable',True))
            def summary():
                _,_,pair=authorize(request,project_id)
                with pair.drafts.store.connect() as db:
                    db.execute('BEGIN')
                    version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
                    if type(version) is not int or not 0<=version<=2**63-1:raise Conflict('control source version invalid')
                    if pair.drafts.store._goal_registration(db)!=(project_id,pair.drafts.data_mode):raise Conflict('control source scope changed')
                authorize(request,project_id)  # Scope may have been revoked during the read.
                return {'current_version':version}
            try:details=await pool.run(summary)
            except ControlError as current:return error_response(current)
            except Exception:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','control source unavailable',True))
            return error_response(ControlError(409,'VERSION_CONFLICT','control state version conflict',False,details))
        except Exception:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','control source unavailable',True))

    @app.post('/api/v1/projects/{project_id}/commands')
    async def commands(request:Request,project_id:str):
        try:
            boundary(request,idempotency=True);payload=await body(request);validate('command_v1_1',payload)
            if type(payload['expected_version']) is not int:raise ProtocolError('actual integer version required')
        except ControlError as error:return error_response(error)
        except ProtocolError:return error_response(ControlError(400,'VALIDATION_ERROR','closed command1.1 required'))
        def execute():
            action=payload['action'];role='operator' if action=='submit_goal' else 'approver'
            token,access,pair=authorize(request,project_id,role);params=payload['parameters'];target=payload['target']
            key=request.headers['idempotency-key'];command_id=control_command_key(
                {'id':access.principal.id,'kind':'human'},project_id,pair.drafts.data_mode,key)
            common={'token':token,'csrf':request.headers['x-csrf-token'],'origin':origin,'idempotency_key':key,'_control_command_id':command_id}
            if action=='submit_goal':
                if target['id']!=project_id:raise ProtocolError('target project mismatch')
                result=pair.drafts.submit(params['goal'],**common,expected_revision=params['expected_revision'],expected_state_version=payload['expected_version'])
            elif action=='approve':
                confirm=params['confirmation']
                if target['id']!=confirm['goal_id'] or payload['expected_version']!=confirm['expected_version']:raise ProtocolError('confirmation target/version mismatch')
                result=pair.approvals.approve(confirm,**common)
            else:
                result=pair.approvals.revoke(**common,goal_id=params['goal_id'],approval_key=target['id'],
                    expected_version=payload['expected_version'],expected_authority_revision=params['expected_authority_revision'],reason=params['reason'])
            return command_dto(command_id,read_receipt(pair.drafts.store,command_id),duplicate=result['duplicate'])
        return await response(execute,status=202,request=request,project_id=project_id)

    @app.post('/api/v1/projects/{project_id}/goals/{goal_id}/approval-confirmations')
    async def confirmations(request:Request,project_id:str,goal_id:str):
        try:
            boundary(request);payload=await body(request)
            validate_schema(obj({'ttl_seconds':{'type':'integer','minimum':1,'maximum':86400}}),payload)
        except ControlError as error:return error_response(error)
        except ProtocolError:return error_response(ControlError(400,'VALIDATION_ERROR','closed confirmation request required'))
        def prepare():
            token,_,pair=authorize(request,project_id,'approver')
            return pair.approvals.prepare(token=token,csrf=request.headers['x-csrf-token'],origin=origin,goal_id=goal_id,ttl_seconds=payload['ttl_seconds'])
        return await response(prepare,request=request,project_id=project_id)

    @app.get('/api/v1/projects/{project_id}/commands/{command_id}')
    async def receipt(request:Request,project_id:str,command_id:str):
        def lookup():
            _,_,pair=authorize(request,project_id)
            validate_schema(ID,command_id)
            return command_dto(command_id,read_receipt(pair.drafts.store,command_id))
        return await response(lookup,request=request,project_id=project_id)

    @app.get('/api/v1/projects/{project_id}/goals')
    async def goals(request:Request,project_id:str):
        try:
            if (set(request.query_params)-{'after','limit'} or any(len(request.query_params.getlist(k))!=1 for k in request.query_params)):
                raise ValueError('ambiguous Hybrid page query')
            raw=request.query_params.get('limit','30')
            if not raw.isascii() or not raw.isdecimal() or len(raw)>2:raise ValueError('invalid Hybrid page size')
            limit=int(raw)
            if not 1<=limit<=50:raise ValueError('invalid Hybrid page size')
            after=request.query_params.get('after','')
            if after:validate_schema(ID,after)
        except (ValueError,ProtocolError):return error_response(ControlError(400,'VALIDATION_ERROR','bounded Hybrid page query required'))
        def lookup():
            authorize(request,project_id)
            result=readers[project_id].goals(after=after,limit=limit)
            authorize(request,project_id)
            readers[project_id].check_current(result['as_of_state_version'])
            authorize(request,project_id)
            return result
        return await response(lookup,request=request,project_id=project_id)

    @app.get('/api/v1/projects/{project_id}/goals/{goal_ref}/review')
    async def review(request:Request,project_id:str,goal_ref:str):
        def lookup():
            authorize(request,project_id,'review')
            validate_schema(ID,goal_ref)
            if request.query_params:raise ControlError(400,'VALIDATION_ERROR','closed review query required')
            result=readers[project_id].review(goal_ref)
            authorize(request,project_id,'review')
            if result is None:raise ControlError(404,'NOT_FOUND','goal not found')
            readers[project_id].check_current(result['as_of_state_version'])
            authorize(request,project_id,'review')
            return result
        return await response(lookup,request=request,project_id=project_id)
