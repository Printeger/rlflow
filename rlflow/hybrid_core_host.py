"""Trusted existing Core-only hosting; no migrations, runtime or cold adoption."""
from contextlib import asynccontextmanager
import asyncio
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urlsplit

from .hybrid_registry import Registry
from .hybrid_protocol import ID,validate_schema
from .hybrid_goals import SECTIONS as GOALS
from .hybrid_authority import ApprovalService,SECTIONS as AUTHORITY
from .hybrid_drafts import DraftService
from .hybrid_control import ControlServices
from .hybrid_agent_requests import AgentRequestService
from .store import Store,Conflict,initial
from .hybrid_reads import ReadBudget
from .web_auth import AuthStore
from .web_api import Project,create_app


@dataclass(frozen=True)
class CoreRegistration:
    root: Path
    project_id: str
    data_mode: str
    store_epoch: str
    registry: Registry


class _Pins:
    def __init__(self):
        self.pid=os.getpid();self.pins=[];self.closed=False;self.closing=False
        self.started=False;self.ready=False

    def acquire(self,root):
        path=root/'runtime/hybrid-core-host.lock'
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or
                    info.st_nlink!=1 or info.st_mode & 0o077 or info.st_size!=0):
                raise PermissionError('private original host owner pin required')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:
            os.close(fd);raise
        self.pins.append((fd,path,(info.st_dev,info.st_ino)))

    def check(self):
        if self.closed or self.closing or os.getpid()!=self.pid:raise PermissionError('original host process required')
        for fd,path,identity in self.pins:
            info=os.fstat(fd);current=path.lstat()
            if ((info.st_dev,info.st_ino)!=identity or (current.st_dev,current.st_ino)!=identity or
                    not stat.S_ISREG(current.st_mode) or current.st_nlink!=1 or
                    current.st_uid!=os.geteuid() or current.st_mode & 0o077):
                raise Conflict('host owner pin changed')

    def close(self):
        # Closing inherited FD in a fork never explicitly unlocks parent's pin.
        self.closing=True
        failures=[];remaining=[]
        for pin in reversed(self.pins):
            fd,path,identity=pin
            try:
                info=os.fstat(fd)
                if (info.st_dev,info.st_ino)!=identity:
                    raise Conflict('original host owner FD replaced')
                os.close(fd)
            except (OSError,Conflict) as error:
                failures.append(error);remaining.append(pin)
        self.pins=list(reversed(remaining));self.closed=not self.pins
        if failures:raise Conflict('original host pin cleanup incomplete') from failures[0]


def create_core_host(registrations,auth,*,origin,max_control_jobs=4,max_streams=8):
    """Explicit trusted SDK startup; only original observed Core facts allowed.

    Auth credentials/Agent tokens are provisioned using existing AuthStore SDK,
    not repository metadata, HTTP self-issuance or a new credential loader.
    Call the returned app's lifespan even when no request has been served.
    """
    if type(auth) is not AuthStore or type(registrations) not in (tuple,list) or not 1<=len(registrations)<=3:
        raise ValueError('bounded trusted Core registrations and original Auth required')
    parsed=urlsplit(origin)
    host='[::1]' if parsed.hostname=='::1' else parsed.hostname
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','::1') or
            parsed.port is None or parsed.netloc!=f'{host}:{parsed.port}' or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('canonical loopback origin required')
    plans=[];roots=set();projects=set();database_ids={}
    for registration in registrations:
        if type(registration) is not CoreRegistration or type(registration.registry) is not Registry:
            raise TypeError('original explicit Core registration required')
        validate_schema(ID,registration.project_id);validate_schema(ID,registration.store_epoch)
        config=json.loads(registration.registry._raw)
        if (config['project_id'],config['data_mode'])!=(registration.project_id,registration.data_mode):
            raise Conflict('original registered catalog scope differs')
        root=Path(registration.root)
        if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True)!=root:
            raise ValueError('existing canonical protected root required')
        for path in (root,root/'runtime'):
            info=path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o077:
                raise PermissionError('private existing Core directories required')
        db_info=(root/'runtime/research.db').lstat()
        if not stat.S_ISREG(db_info.st_mode) or db_info.st_nlink!=1:
            raise PermissionError('unaliased original Core database required')
        identity=(db_info.st_dev,db_info.st_ino)
        if identity in database_ids.values():raise Conflict('distinct original Core databases required')
        database_ids[root]=identity
        if root in roots or registration.project_id in projects:raise ValueError('distinct original Core scopes required')
        roots.add(root);projects.add(registration.project_id);plans.append((root,registration))
    pins=_Pins()
    try:
        for root,_ in sorted(plans,key=lambda row:str(row[0])):pins.acquire(root)
        stores={}
        # All existing sources are checked before any Core/Auth owner binding
        # or inbox creation. attach_existing performs no DDL/reset/recovery.
        for root,registration in plans:
            store=Store.attach_existing(root,project_id=registration.project_id,data_mode=registration.data_mode)
            if store._existing_identity!=database_ids[root] or store.db.lstat().st_nlink!=1:
                raise Conflict('original Core database identity changed')
            if store.store_epoch!=registration.store_epoch:raise Conflict('original Core epoch differs')
            with store.read_connection() as db:
                allowed=(*GOALS,*AUTHORITY)
                placeholders=','.join('?' for _ in allowed)
                if db.execute(f'SELECT 1 FROM projection WHERE object_key!=? AND section NOT IN ({placeholders}) LIMIT 1',
                        ('',*allowed)).fetchone() or db.execute('SELECT enabled FROM observation_meta WHERE singleton=1').fetchone()[0]:
                    raise Conflict('Core-only hosting cannot adopt execution or legacy state')
                markers=set(allowed)|{name for name,value in initial().items() if type(value) is dict}|{'paused','enabled'}
                rows=db.execute("SELECT CASE WHEN length(CAST(section AS BLOB))<=160 THEN section END FROM projection WHERE object_key='' LIMIT 32").fetchall()
                if len(rows)>len(markers):raise Conflict('closed Core marker census required')
                read=ReadBudget(db,256*1024)
                for row in rows:
                    section=row[0]
                    if section not in markers:raise Conflict('unknown Core marker refused')
                    value=read.object(section,'')
                    if (section in ('paused','enabled') and type(value) is not bool or
                            section=='enabled' and value or
                            section not in ('paused','enabled') and value!={}):
                        raise Conflict('nonempty or invalid Core marker refused')
            stores[registration.project_id]=store
        pairs={};requests={};views=[]
        for root,registration in plans:
            store=stores[registration.project_id]
            draft=DraftService(store,auth,project_id=registration.project_id,data_mode=registration.data_mode,origin=origin)
            approval=ApprovalService(store,auth,registration.registry,project_id=registration.project_id,
                data_mode=registration.data_mode,origin=origin)
            pairs[registration.project_id]=ControlServices(draft,approval)
            requests[registration.project_id]=AgentRequestService(draft)
            views.append(Project(registration.project_id,str(root),registration.data_mode))
        pins.check()
        app=create_app(views,auth,origin=origin,control_services=pairs,agent_request_services=requests,
            max_control_jobs=max_control_jobs,max_streams=max_streams)
        original=app.router.lifespan_context
        @asynccontextmanager
        async def lifespan(current):
            if os.getpid()!=pins.pid:
                pins.close()  # Fork closes inherited FDs, no parent pools.
                raise PermissionError('original host process required')
            pins.check()
            if pins.started:raise Conflict('one original host lifespan required')
            pins.started=True
            context=original(current)
            try:await context.__aenter__()
            except BaseException:
                pins.close();raise
            pins.ready=True
            try:yield
            finally:
                pins.closing=True  # Reject new HTTP before draining.
                errors=sys.exc_info()
                async def drain():
                    # A failed/cancelled owned drain retains the pins. Only a
                    # true original completion may release this owner fence.
                    await context.__aexit__(*errors)
                    pins.close()
                task=asyncio.create_task(drain())
                app.state.core_host_drain=task
                task.add_done_callback(lambda future:None if future.cancelled() else future.exception())
                await asyncio.shield(task)  # Waiter cancellation is not exit.
        app.router.lifespan_context=lifespan
        @app.middleware('http')
        async def owner_guard(request,call_next):
            from fastapi.responses import JSONResponse
            try:
                pins.check()
                if not pins.ready:raise PermissionError('original host lifespan required')
            except (OSError,Conflict,PermissionError):
                return JSONResponse({'detail':'original Core host owner unavailable'},status_code=503)
            return await call_next(request)
        return app
    except BaseException:
        pins.close();raise
