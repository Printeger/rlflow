import socket
import threading
import time

import httpx
import pytest
import uvicorn

from rlflow.observation import ObservationReader, enable
from rlflow.store import Store
from rlflow.web import load_config, local_origin, provision
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Principal


def test_private_configuration_and_explicit_observation_migration(tmp_path):
    store = Store(tmp_path / "state")
    path = tmp_path / "web.json"
    phrase = "synthetic loopback test passphrase"
    provision(store.root, "project_local", path, phrase, data_mode="fixture")
    assert path.stat().st_mode & 0o777 == 0o600
    assert phrase not in path.read_text()
    origin, projects, auth = load_config(path)
    assert auth.login("local", phrase)
    assert ObservationReader(store.root).head()["project_id"] == "project_local"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        provision(store.root, "project_local", path, phrase)
    assert path.read_bytes() == before
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_config(path)
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_config(link)
    for origin in ("http://0.0.0.0:8765", "http://example.com:8765", "http://127.0.0.1", "http://127.0.0.1:8765/", "https://127.0.0.1:8765"):
        with pytest.raises(ValueError):
            local_origin(origin)


def test_real_loopback_http_sse_commit_and_last_event_id_reconnect(tmp_path):
    store = Store(tmp_path / "state")
    enable(store, "project_tcp", data_mode="fixture")
    auth = AuthStore()
    token, _ = auth.issue_bearer(Principal("probe", "agent", frozenset({"viewer"}), frozenset({"project_tcp"})))
    # Pass an already-bound private socket to avoid a port selection race.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    app = create_app([Project("project_tcp", str(store.root), "fixture")], auth, origin=origin,
                     stream_options={"poll": 0.01, "heartbeat": 0.05})
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, proxy_headers=False, access_log=False, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 3
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(base_url=origin, headers={"Authorization": f"Bearer {token}"}, timeout=2) as client:
            snapshot = client.get("/api/v1/projects/project_tcp/snapshot").json()
            with client.stream("GET", "/api/v1/projects/project_tcp/events", params={"after": snapshot["cursor"]}) as response:
                assert response.status_code == 200
                store.transact_objects("USAGE_OBSERVED", "tcp_commit", [("usage", "s")], lambda s: s.setdefault("usage", {}).update(s={"input_tokens": 5}))
                lines = []
                for line in response.iter_lines():
                    lines.append(line)
                    if not line and any("event: domain" == l for l in lines):
                        break
                assert any('"input_tokens":5' in line for line in lines)
                cursor = next(line[4:] for line in lines if line.startswith("id: "))
            with client.stream("GET", "/api/v1/projects/project_tcp/events", params={"after": "invalid"}, headers={"Last-Event-ID": cursor}) as response:
                lines = []
                for line in response.iter_lines():
                    lines.append(line)
                    if not line and "event: heartbeat" in lines:
                        break
                assert "event: domain" not in lines and not any(line.startswith("id:") for line in lines)
    finally:
        server.should_exit = True
        thread.join(timeout=3)
        sock.close()
    assert not thread.is_alive()
