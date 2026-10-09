"""Read-only local dashboard API. Does not instantiate Store or run a scheduler."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from starlette.staticfiles import StaticFiles

from .hybrid_protocol import ProtocolError
from .live_stream import LiveStream
from .observation import ObservationReader

COOKIE = "rlflow_session"


class SameOriginBoundary:
    """Pure ASGI: preserve SSE deadlines all the way to the socket send."""

    def __init__(self, app, *, origin, host, control_enabled=False):
        self.app, self.origin, self.host = app, origin, host
        self.control_enabled=control_enabled

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {}
        repeated_boundary_header = False
        for key, value in scope["headers"]:
            if key in {b"host", b"origin", b"authorization", b"cookie"} and key in headers:
                repeated_boundary_header = True
            headers[key] = value

        async def safe_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                security = {b"cache-control": b"no-store", b"x-content-type-options": b"nosniff",
                            b"referrer-policy": b"no-referrer", b"content-security-policy":
                            b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"}
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k not in security] + list(security.items())
            await send(message)

        if repeated_boundary_header or headers.get(b"host") != self.host.encode() or (b"origin" in headers and headers[b"origin"] != self.origin.encode()):
            path=scope['path']
            if self.control_enabled and path.startswith('/api/v1/projects/') and ('/commands' in path or path.endswith('/approval-confirmations')):
                from .hybrid_control import ControlError, error_response
                return await error_response(ControlError(403,'PERMISSION_DENIED','same-origin request required'))(scope,receive,safe_send)
            return await JSONResponse({"detail": "same-origin request required"}, status_code=403)(scope, receive, safe_send)
        return await self.app(scope, receive, safe_send)


@dataclass(frozen=True)
class Project:
    id: str
    root: str
    data_mode: str = "live"


def create_app(projects, auth, *, origin="http://127.0.0.1:8765", max_streams=8, stream_options=None,
               control_services=None, max_control_jobs=4, fixture_task_readers=None,
               fixture_runtime_services=None,cpu_assessment_readers=None,candidate_output_readers=None,
               fixed_unit_telemetry=None,cpu_unit_services=None,engineering_unit_services=None,
               delivery_evidence_readers=None):
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("origin must be a canonical HTTP origin")
    if not 1 <= max_streams <= 16:
        raise ValueError("invalid stream limit")
    projects = tuple(projects)
    registry = {p.id: p for p in projects}
    if len(registry) != len(projects) or len(registry) > 128 or any(p.data_mode not in {"live", "fixture"} for p in projects):
        raise ValueError("invalid project registry")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    from .hybrid_resource_telemetry import FixedUnitTelemetry
    fixed_unit_telemetry = dict(fixed_unit_telemetry or {})
    for key, observer in fixed_unit_telemetry.items():
        project = registry.get(key)
        if (type(observer) is not FixedUnitTelemetry or project is None or
                (observer.project_id,observer.data_mode,str(observer.root)) !=
                (key,project.data_mode,str(Path(project.root).resolve(strict=True)))):
            raise ValueError('original telemetry startup project binding required')
        observer._original()
    active_streams = 0

    app.add_middleware(SameOriginBoundary, origin=origin, host=parsed.netloc,
                       control_enabled=control_services is not None or fixture_runtime_services is not None or cpu_unit_services is not None or engineering_unit_services is not None)

    def access(request):
        authorization = request.headers.get("authorization")
        if authorization:
            prefix, _, token = authorization.partition(" ")
            resolved = auth.resolve(token, "bearer") if prefix == "Bearer" else None
            method = "bearer"
        else:
            token, method = request.cookies.get(COOKIE), "session"
            resolved = auth.resolve(token, method)
        if resolved is None:
            raise HTTPException(401, "authentication required")
        return token, method, resolved

    async def reader_for(request, project_id):
        _, _, resolved = access(request)
        if not resolved.principal.allows(project_id) or project_id not in registry:
            raise HTTPException(404, "project not found")
        project = registry[project_id]
        reader = ObservationReader(project.root, expected_project_id=project_id, expected_data_mode=project.data_mode)
        try:
            head = await asyncio.to_thread(reader.head)
        except Exception:
            raise HTTPException(503, "observation source unavailable") from None
        if head["project_id"] != project_id or head["data_mode"] != project.data_mode:
            raise HTTPException(503, "observation identity mismatch")
        if (project_id in fixed_unit_telemetry and
                head['cursor'].rsplit(':',1)[0] != fixed_unit_telemetry[project_id].store_epoch):
            raise HTTPException(503, 'observation identity mismatch')
        return reader

    async def read(call, **kwargs):
        try:
            return await asyncio.to_thread(call, **kwargs)
        except ProtocolError as exc:
            raise HTTPException(409 if exc.code == "RESYNC_REQUIRED" else 404 if exc.code == "NOT_FOUND" else 400, "observation request rejected") from None
        except Exception:
            raise HTTPException(503, "observation source unavailable") from None

    @app.get("/health")
    async def health():
        return {"ready": True}

    @app.post("/api/v1/login")
    async def login(request: Request):
        if request.headers.get("origin") != origin or request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(403, "same-origin JSON login required")
        chunks, size = [], 0
        try:
            async with asyncio.timeout(2):
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 4096:
                        raise HTTPException(413, "login payload too large")
                    chunks.append(chunk)
        except TimeoutError:
            raise HTTPException(408, "login payload timeout") from None
        try:
            payload = json.loads(b"".join(chunks))
            if not isinstance(payload, dict) or set(payload) != {"principal_id", "passphrase"}:
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, "invalid login payload") from None
        result = await asyncio.to_thread(auth.login, payload["principal_id"], payload["passphrase"])
        if result is None:
            raise HTTPException(401, "login rejected")
        token, resolved = result
        response = JSONResponse({"csrf_token": resolved.csrf, "expires_in": auth.ttl})
        response.set_cookie(COOKIE, token, max_age=auth.ttl, httponly=True, secure=parsed.scheme == "https", samesite="strict", path="/")
        return response

    @app.get("/api/v1/session")
    async def session(request: Request):
        _, _, resolved = access(request)
        return {"principal_id": resolved.principal.id, "kind": resolved.principal.kind,
                "roles": sorted(resolved.principal.roles), "projects": sorted(resolved.principal.projects),
                "csrf_token": resolved.csrf}

    @app.post("/api/v1/logout")
    async def logout(request: Request):
        token, method, resolved = access(request)
        if request.headers.get("origin") != origin or method != "session" or not resolved.csrf or request.headers.get("x-csrf-token") != resolved.csrf:
            raise HTTPException(403, "same-origin session CSRF required")
        auth.revoke(token)
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(COOKIE, path="/", httponly=True, secure=parsed.scheme == "https", samesite="strict")
        return response

    @app.get("/api/v1/projects")
    async def list_projects(request: Request):
        _, _, resolved = access(request)
        return {"items": [{"id": p.id, "data_mode": p.data_mode} for p in projects if resolved.principal.allows(p.id)]}

    @app.get("/api/v1/projects/{project_id}/snapshot")
    async def snapshot(request: Request, project_id: str):
        reader = await reader_for(request, project_id)
        return await read(reader.snapshot)

    @app.get("/api/v1/projects/{project_id}/objects")
    async def objects(request: Request, project_id: str, kind: str | None = None, after: str = "", limit: int = 50):
        reader = await reader_for(request, project_id)
        return await read(reader.page, kind=kind, after=after, limit=limit, include_cursor=True)

    @app.get("/api/v1/projects/{project_id}/telemetry")
    async def telemetry(request: Request, project_id: str):
        reader = await reader_for(request, project_id)
        if project_id in fixed_unit_telemetry:
            value = await read(fixed_unit_telemetry[project_id].latest)
            _, _, current = access(request)  # Recheck after optional source IO.
            if not current.principal.allows(project_id):
                raise HTTPException(404, 'project not found')
            return value
        return await read(reader.telemetry)

    @app.get("/api/v1/projects/{project_id}/domain-events/{event_id}")
    async def domain_event(request: Request, project_id: str, event_id: str):
        reader = await reader_for(request, project_id)
        return await read(reader.event, event_id=event_id)

    @app.get("/api/v1/projects/{project_id}/logs")
    async def logs(request: Request, project_id: str, severity: str | None = None, kind: str | None = None,
                   object_id: str | None = None, after: str = "", limit: int = 50):
        from .public_logs import page
        reader = await reader_for(request, project_id)
        return await read(page,reader=reader,severity=severity,kind=kind,object_id=object_id,after=after,limit=limit)

    @app.get("/api/v1/projects/{project_id}/logs/{log_id}")
    async def log_body(request: Request, project_id: str, log_id: str):
        from .public_logs import body
        reader = await reader_for(request, project_id)
        return await read(body,reader=reader,log_id=log_id)

    @app.get("/api/v1/projects/{project_id}/events")
    async def events(request: Request, project_id: str, after: str = ""):
        nonlocal active_streams
        reader = await reader_for(request, project_id)
        token, method, resolved = access(request)
        if active_streams >= max_streams:
            raise HTTPException(429, "stream capacity reached")
        def authorized():
            current = auth.resolve(token, method)
            return current is not None and current.principal.allows(project_id)

        def release():
            nonlocal active_streams
            active_streams -= 1

        response = LiveStream(reader, request.headers.get("last-event-id", after), authorized, release,
                              telemetry_query=(fixed_unit_telemetry[project_id].latest
                                               if project_id in fixed_unit_telemetry else None),
                              **(stream_options or {}))
        active_streams += 1
        return response

    if control_services is not None:
        from .hybrid_control import install
        install(app,control_services,registry,auth,origin=origin,max_jobs=max_control_jobs)

    if fixture_task_readers is not None:
        from .hybrid_fixture_runtime_reads import install as install_fixture_reads
        install_fixture_reads(app,fixture_task_readers,registry,auth)

    if fixture_runtime_services is not None:
        from .hybrid_fixture_runtime_control import install as install_fixture_control
        install_fixture_control(app,fixture_runtime_services,registry,auth,origin=origin,max_jobs=max_control_jobs)

    if cpu_assessment_readers is not None:
        from .hybrid_cpu_assessment_reads import install as install_cpu_reads
        install_cpu_reads(app,cpu_assessment_readers,registry,auth)

    if candidate_output_readers is not None:
        from .hybrid_candidate_output_reads import install as install_candidate_reads
        install_candidate_reads(app,candidate_output_readers,registry,auth)

    if delivery_evidence_readers is not None:
        from .hybrid_delivery_evidence import install as install_delivery_reads
        install_delivery_reads(app,delivery_evidence_readers,registry,auth)

    if cpu_unit_services is not None:
        from .hybrid_cpu_unit_control import install as install_cpu_units
        install_cpu_units(app,cpu_unit_services,registry,auth,origin=origin,max_jobs=max_control_jobs)
    if engineering_unit_services is not None:
        from .hybrid_engineering_unit_control import install as install_engineering_units
        install_engineering_units(app,engineering_unit_services,registry,auth,origin=origin,max_jobs=max_control_jobs)

    static = Path(__file__).with_name("static")
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static / "index.html")
    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
