import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from rlflow.observation import ObservationReader, enable
from rlflow.hybrid_protocol import validate
from rlflow.store import Store
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Credential, Principal

ORIGIN = "http://127.0.0.1:8765"
PHRASE = "synthetic local testing passphrase"


@pytest.fixture
def web(tmp_path):
    store = Store(tmp_path / "fixture")
    enable(store, "project_one", data_mode="fixture")
    principal = Principal("local", "human", frozenset({"viewer"}), frozenset({"project_one"}))
    auth = AuthStore([Credential.create(principal, PHRASE)])
    projects = [Project("project_one", str(store.root), "fixture"), Project("project_two", "/DO_NOT_OPEN", "live")]
    app = create_app(projects, auth, stream_options={"poll": 0.01, "heartbeat": 0.02, "send_timeout": 0.05})
    with TestClient(app, base_url=ORIGIN) as client:
        yield store, auth, app, client


def login(client):
    return client.post("/api/v1/login", headers={"Origin": ORIGIN}, json={"principal_id": "local", "passphrase": PHRASE})


def test_anonymous_routes_and_same_origin_dns_boundary(web):
    store, auth, app, client = web
    assert client.get("/health").json() == {"ready": True}
    for path in ("/api/v1/projects", "/api/v1/session", "/api/v1/projects/project_one/snapshot", "/api/v1/projects/project_one/objects", "/api/v1/projects/project_one/events"):
        assert client.get(path).status_code == 401
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 404
    assert client.get("/health", headers={"Host": "evil.example:8765"}).status_code == 403
    assert client.get("/health", headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/v1/login", json={"principal_id": "local", "passphrase": PHRASE}).status_code == 403
    assert client.post("/api/v1/login", headers={"Origin": "http://evil.example"}, json={}).status_code == 403


def test_cookie_scope_csrf_and_readonly_snapshot(web):
    store, auth, app, client = web
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert client.get("/api/v1/projects").json() == {"items": [{"id": "project_one", "data_mode": "fixture"}]}
    version = store.version()
    snapshot = client.get("/api/v1/projects/project_one/snapshot")
    expected = ObservationReader(store.root).snapshot()
    assert {k: v for k, v in snapshot.json().items() if k != "server_time"} == {k: v for k, v in expected.items() if k != "server_time"}
    assert snapshot.json()["data_mode"] == "fixture"
    assert client.get("/api/v1/projects/project_two/snapshot").status_code == 404
    assert client.get("/api/v1/projects/project_two/objects").status_code == 404
    assert client.get("/api/v1/projects/project_two/events").status_code == 404
    assert client.post("/api/v1/projects/project_one/commands", json={}).status_code == 404
    assert client.get("/api/v1/projects/project_one/objects?limit=201").status_code == 400
    assert client.post("/api/v1/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}).status_code == 200
    assert client.get("/api/v1/projects").status_code == 401
    assert store.version() == version
    assert snapshot.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in snapshot.headers["content-security-policy"]


def test_bearer_is_header_only_and_machine_cannot_login(web):
    store, auth, app, client = web
    agent = Principal("robot", "agent", frozenset({"viewer"}), frozenset({"project_one"}))
    token, _ = auth.issue_bearer(agent)
    assert client.get(f"/api/v1/projects?token={token}").status_code == 401
    assert client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    client.cookies.set("rlflow_session", token)
    assert client.get("/api/v1/projects").status_code == 401
    assert client.post("/api/v1/logout", headers={"Origin": ORIGIN, "Authorization": f"Bearer {token}"}).status_code == 403


def test_identity_mismatch_missing_source_and_payload_errors_do_not_leak(web):
    store, auth, app, client = web
    assert login(client).status_code == 200
    app2 = create_app([Project("project_one", str(store.root), "live")], auth)
    with TestClient(app2, base_url=ORIGIN, cookies=client.cookies) as other:
        response = other.get("/api/v1/projects/project_one/snapshot")
        assert response.status_code == 503
        assert str(store.root) not in response.text
    assert client.post("/api/v1/login", headers={"Origin": ORIGIN, "Content-Type": "application/json"}, content="x" * 4097).status_code == 413
    assert client.post("/api/v1/login", headers={"Origin": ORIGIN}, json=[]).status_code == 400
    assert client.post("/api/v1/login", headers={"Origin": ORIGIN}, json={"principal_id": "local", "passphrase": PHRASE, "extra": "reject"}).status_code == 400
    assert client.post("/api/v1/login", headers={"Origin": ORIGIN, "Content-Type": "application/json"}, content=b'{"principal_id":"local","passphrase":"\\ud800"}').status_code == 401


def test_identity_is_rechecked_inside_snapshot_transaction_after_head(web, tmp_path, monkeypatch):
    store, auth, app, client = web
    other = Store(tmp_path / "other")
    enable(other, "project_two", data_mode="fixture")
    original = ObservationReader.head
    def swapped_head(self):
        head = original(self)
        self.db = other.root / "runtime" / "research.db"
        return head
    monkeypatch.setattr(ObservationReader, "head", swapped_head)
    assert login(client).status_code == 200
    response = client.get("/api/v1/projects/project_one/snapshot")
    assert response.status_code == 409
    assert "project_two" not in response.text


async def run_stream(app, token, query, stop_when, *, last_event_id=None, stall=False):
    messages = []
    ended = asyncio.Event()
    headers = [(b"host", b"127.0.0.1:8765"), (b"authorization", f"Bearer {token}".encode())]
    if last_event_id:
        headers.append((b"last-event-id", last_event_id.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": "/api/v1/projects/project_one/events", "raw_path": b"/api/v1/projects/project_one/events",
             "query_string": query.encode(), "headers": headers, "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1)}

    async def receive():
        await ended.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            if stall:
                await asyncio.Event().wait()
            if stop_when(message["body"]):
                ended.set()

    await asyncio.wait_for(app(scope, receive, send), 1)
    return messages


def test_real_asgi_sse_snapshot_seam_reconnect_headers_and_no_heartbeat_id(web):
    store, auth, app, client = web
    token, _ = auth.issue_bearer(Principal("robot", "agent", frozenset({"viewer"}), frozenset({"project_one"})))
    snapshot = ObservationReader(store.root).snapshot()
    store.transact_objects("USAGE_OBSERVED", "u1", [("usage", "s1")], lambda s: s.setdefault("usage", {}).update(s1={"input_tokens": 3}))
    cursor = ObservationReader(store.root).head()["cursor"]
    messages = asyncio.run(run_stream(app, token, "after=" + snapshot["cursor"], lambda b: b"event: heartbeat" in b))
    body = b"".join(m.get("body", b"") for m in messages)
    assert body.count(b"event: domain") == 1 and f"id: {cursor}".encode() in body
    heartbeat = body.split(b"event: heartbeat", 1)[1]
    assert b"id:" not in heartbeat
    validate("Heartbeat", json.loads(heartbeat.split(b"data: ", 1)[1].split(b"\n", 1)[0]))
    headers = dict(messages[0]["headers"])
    assert b"content-length" not in headers and headers[b"content-type"].startswith(b"text/event-stream")
    second = asyncio.run(run_stream(app, token, "after=invalid", lambda b: b"event: heartbeat" in b, last_event_id=cursor))
    assert b"event: domain" not in b"".join(m.get("body", b"") for m in second)


def test_invalid_cursor_sends_resync_and_stalled_actual_send_releases_slot(web):
    store, auth, app, client = web
    token, _ = auth.issue_bearer(Principal("robot", "agent", frozenset({"viewer"}), frozenset({"project_one"})))
    messages = asyncio.run(run_stream(app, token, "after=invalid", lambda b: b"resync_required" in b))
    assert b"RESYNC_REQUIRED" in messages[-1]["body"] and messages[-1]["more_body"] is False
    assert b"id:" not in messages[-1]["body"]
    cursor = ObservationReader(store.root).head()["cursor"]
    for _ in range(10):
        # More than max_streams repetitions prove disconnected/timed-out slots
        # are reclaimed. The stall is at the OUTER ASGI socket-facing send.
        stalled = asyncio.run(run_stream(app, token, "after=" + cursor, lambda b: False, stall=True))
        assert stalled[0]["status"] == 200
