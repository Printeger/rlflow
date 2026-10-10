"""Trusted read-only installed history. No execution/recovery capability adoption."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from .hybrid_registry import Registry
from .hybrid_protocol import ID, ProtocolError, validate_schema
from .hybrid_cpu_assessment_reads import CpuAssessmentReader
from .hybrid_candidate_output_reads import CandidateOutputReader
from .hybrid_delivery_evidence import DeliveryEvidenceReader
from .hybrid_client_execution_report import read_public
from .hybrid_control import ControlError, ControlPool, error_response
from .store import Store, Conflict
from .web_api import Project, create_app
from .web_auth import AuthStore


@dataclass(frozen=True)
class ColdResultRegistration:
    root: Path
    project_id: str
    store_epoch: str
    registry: Registry
    kind: str


def create_cold_result_host(registrations, auth, *, origin, max_reads=2):
    """Explicit protected registrations, fresh original auth, no writable services.

    SQLite may maintain WAL/SHM while reading; no domain event, settlement,
    migration, writer lock, runtime ownership or process control is requested.
    Run lifespan once. Reads from active databases are still as-of, not STOP.
    """
    if (type(auth) is not AuthStore or type(registrations) not in (tuple,list)
            or not 1 <= len(registrations) <= 3 or type(max_reads) is not int or not 1 <= max_reads <= 4):
        raise ValueError('bounded original cold registrations and Auth required')
    parsed=urlsplit(origin)
    host='[::1]' if parsed.hostname=='::1' else parsed.hostname
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','::1') or parsed.port is None
            or parsed.netloc!=f'{host}:{parsed.port}' or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('canonical loopback cold origin required')
    readers={};projects=[];identities=set();roots=set();bindings=[]
    for registration in registrations:
        if type(registration) is not ColdResultRegistration or type(registration.registry) is not Registry:
            raise TypeError('explicit original cold registration required')
        validate_schema(ID,registration.project_id);validate_schema(ID,registration.store_epoch)
        config=json.loads(registration.registry._raw)
        if ((config['project_id'],config['data_mode'])!=(registration.project_id,'fixture')
                or registration.kind not in ('CPU_TRIAL','ENGINEERING')):
            raise Conflict('cold registered original catalog scope/kind differs')
        root=Path(registration.root)
        if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True)!=root:
            raise ValueError('canonical existing cold root required')
        for path in (root,root/'runtime'):
            info=path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o077:
                raise PermissionError('private existing cold directories required')
        info=(root/'runtime/research.db').lstat();identity=(info.st_dev,info.st_ino)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid()
                or info.st_mode & 0o077):raise PermissionError('private unaliased cold database required')
        if root in roots or registration.project_id in readers or identity in identities:
            raise Conflict('distinct cold original scopes required')
        store=Store.attach_existing(root,project_id=registration.project_id,data_mode='fixture')
        if store._existing_identity!=identity or store.store_epoch!=registration.store_epoch:
            raise Conflict('cold original database identity/epoch differs')
        source=(CpuAssessmentReader if registration.kind=='CPU_TRIAL' else CandidateOutputReader)(
            store,registration.registry,project_id=registration.project_id,store_epoch=registration.store_epoch)
        reader=DeliveryEvidenceReader(source)
        with source.snapshot():pass
        directories=tuple((path,(path.lstat().st_dev,path.lstat().st_ino)) for path in (root,root/'runtime'))
        bindings.append((root,identity,reader,registration.store_epoch,directories))
        readers[registration.project_id]=reader;roots.add(root);identities.add(identity)
        projects.append(Project(registration.project_id,str(root),'fixture'))
    # Only this report endpoint uses the dedicated bounded pool. Do not install
    # less-bounded alternate result endpoints or a writable Agent inbox.
    app=create_app(projects,auth,origin=origin)
    pid=os.getpid();pool=ControlPool(max_reads);started=False;ready=False;closing=False
    def pure():
        if os.getpid()!=pid or not ready or closing:
            raise Conflict('original cold host unavailable')
        for root,identity,reader,epoch,directories in bindings:
            if (reader.store.root!=root or reader.store.db!=root/'runtime/research.db'
                    or reader.store._existing_identity!=identity or reader.store.store_epoch!=epoch):
                raise Conflict('cold original Store registration changed')
            for directory,directory_identity in directories:
                info=directory.lstat()
                if ((info.st_dev,info.st_ino)!=directory_identity or not stat.S_ISDIR(info.st_mode)
                        or info.st_uid!=os.geteuid() or info.st_mode & 0o077):
                    raise Conflict('cold protected directory changed')
            info=(root/'runtime/research.db').lstat()
            if ((info.st_dev,info.st_ino)!=identity or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink!=1 or info.st_uid!=os.geteuid() or info.st_mode & 0o077):
                raise Conflict('cold protected database changed')
            reader._original()
    @asynccontextmanager
    async def lifespan(current):
        nonlocal started,ready,closing
        if os.getpid()!=pid or started:raise Conflict('one original cold host lifespan required')
        started=True;ready=True
        try:yield
        finally:
            closing=True;ready=False
            task=asyncio.create_task(pool.close());current.state.cold_result_drain=task
            task.add_done_callback(lambda future:None if future.cancelled() else future.exception())
            await asyncio.shield(task)
    app.router.lifespan_context=lifespan
    @app.middleware('http')
    async def guard(request,call_next):
        try:pure()
        except (OSError,Conflict):
            return JSONResponse({'detail':'original cold host unavailable'},status_code=503)
        return await call_next(request)
    def scoped(request,project,kind):
        pure()  # Reject inherited/closed/rebound sources before Auth/SQL/locks.
        header=request.headers.get('authorization')
        if header:
            prefix,_,token=header.partition(' ')
            access=(auth.resolve(token,'request') or auth.resolve(token,'bearer')) if prefix=='Bearer' else None
        else:access=auth.resolve(request.cookies.get('rlflow_session'),'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        reader=readers.get(project)
        if reader is None or reader.kind!=kind or not access.principal.allows(project):
            raise ControlError(404,'NOT_FOUND','original cold scope not found')
        return reader
    @app.get('/api/v1/projects/{project_id}/execution-report/{kind}/{source_id}')
    async def report(request:Request,project_id:str,kind:str,source_id:str):
        def call():
            if request.query_params:raise ControlError(400,'VALIDATION_ERROR','closed original cold query required')
            reader=scoped(request,project_id,kind)
            value=read_public(reader,source_id)
            if scoped(request,project_id,kind) is not reader:raise Conflict('cold registration changed')
            return value
        try:return JSONResponse(await pool.run(call))
        except ControlError as error:return error_response(error)
        except ProtocolError:return error_response(ControlError(400,'VALIDATION_ERROR','bounded original source required'))
        except Exception:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','original cold source unavailable',True))
    return app
