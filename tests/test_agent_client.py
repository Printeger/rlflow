from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest
import uvicorn

from rlflow.agent_client import AgentClient, ClientError, closed_json, read_regular
from rlflow.hybrid_agent_requests import AgentRequestService
from rlflow.web_api import create_app
from rlflow.web_auth import Principal
from tests.test_hybrid_control_api import setup as core_setup, PHRASE


def config(root, origin, *, project='project_fixture'):
    project_root = root / 'target_project'; project_root.mkdir()
    directory = project_root / '.rlflow'; directory.mkdir()
    (directory / 'project.yaml').write_text(json.dumps({'schema_version': '1.0', 'project_id': project, 'control_origin': origin}))
    return project_root


@contextmanager
def hosted(root):
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    store, auth, proposal, _, pair, projects, _ = core_setup(root, origin=origin)
    service = AgentRequestService(pair.drafts)
    token, _ = auth.issue_request_token(Principal('client_agent', 'agent', {'viewer'}, {'project_fixture'}), ttl=50)
    app = create_app(projects, auth, origin=origin, control_services={'project_fixture': pair},
                     agent_request_services={'project_fixture': service})
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield store, auth, proposal, service, {'RLFLOW_CONTROL_ORIGIN': origin, 'RLFLOW_REQUEST_TOKEN': token}
    finally:
        server.should_exit = True; thread.join(5); sock.close()
        assert not thread.is_alive()


def test_real_loopback_project_cwd_client_human_forward_and_report(tmp_path):
    with hosted(tmp_path) as (store, auth, proposal, service, env):
        root = config(tmp_path, env['RLFLOW_CONTROL_ORIGIN'])
        client = AgentClient(cwd=root, environ=env)
        before = store.audit(); saved = client.submit_goal(proposal, key='same_original_key')
        assert saved['status'] == 'AWAITING_HUMAN' and store.audit() == before
        assert client.get_status(saved['request_id']) == saved
        assert client.submit_goal(proposal, key='same_original_key') == saved
        token, access = auth.login('operator', PHRASE)
        accepted = service.forward(saved['request_id'], request_hash=saved['request_hash'], expected_version=0,
            token=token, csrf=access.csrf, origin=env['RLFLOW_CONTROL_ORIGIN'])
        report = client.get_report(saved['request_id'])
        assert report['status'] == 'ADOPTED' and report['result'] == accepted['result']
        assert report['result']['result']['state'] == 'DRAFT' and store.version() == 1
        assert not store.objects('sessions') and not store.objects('jobs') and not store.objects('tasks')
        assert not (root / 'runtime').exists()


def test_actual_single_cli_submit_then_status_without_local_core_or_secret_output(tmp_path):
    with hosted(tmp_path) as (store, auth, proposal, service, env):
        root = config(tmp_path, env['RLFLOW_CONTROL_ORIGIN'])
        proposal_path = root / 'proposal.json'; proposal_path.write_text(json.dumps(proposal))
        environment = {**os.environ, **env, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        call = subprocess.run([sys.executable, '-m', 'rlflow.cli', 'client', 'submit-goal', '--proposal', str(proposal_path), '--key', 'cli_original'],
            cwd=root, env=environment, capture_output=True, text=True, timeout=10)
        assert call.returncode == 0, call.stderr
        saved = json.loads(call.stdout); assert saved['status'] == 'AWAITING_HUMAN' and store.version() == 0
        token, access = auth.login('operator', PHRASE)
        service.forward(saved['request_id'], request_hash=saved['request_hash'], expected_version=0,
            token=token, csrf=access.csrf, origin=env['RLFLOW_CONTROL_ORIGIN'])
        read = subprocess.run([sys.executable, '-m', 'rlflow.cli', 'client', 'report', '--request', saved['request_id']],
            cwd=root, env=environment, capture_output=True, text=True, timeout=10)
        assert read.returncode == 0 and json.loads(read.stdout)['status'] == 'ADOPTED'
        assert env['RLFLOW_REQUEST_TOKEN'] not in call.stdout + call.stderr + read.stdout + read.stderr
        assert PHRASE not in call.stdout + read.stdout
        assert sorted(p.name for p in root.iterdir()) == ['.rlflow', 'proposal.json']


@pytest.mark.parametrize('change', ['origin', 'remote', 'userinfo', 'proxy', 'config_secret', 'duplicate', 'symlink', 'missing'])
def test_untrusted_configuration_cannot_redirect_credentials(tmp_path, change):
    origin = 'http://127.0.0.1:8765'; root = config(tmp_path, origin)
    env = {'RLFLOW_CONTROL_ORIGIN': origin, 'RLFLOW_REQUEST_TOKEN': 'synthetic_token_never_sent_1234'}
    path = root / '.rlflow' / 'project.yaml'
    data = json.loads(path.read_text())
    if change == 'origin': data['control_origin'] = 'http://127.0.0.1:9999'
    elif change in ('remote', 'userinfo'):
        data['control_origin'] = env['RLFLOW_CONTROL_ORIGIN'] = 'http://example.invalid:8765' if change == 'remote' else 'http://user@127.0.0.1:8765'
    elif change == 'proxy': data['control_origin'] = env['RLFLOW_CONTROL_ORIGIN'] = 'http://127.0.0.1:8765/path'
    elif change == 'config_secret': data['passphrase'] = 'forbidden'
    elif change == 'duplicate': path.write_text('schema_version: "1.0"\nproject_id: project_fixture\nproject_id: altered\ncontrol_origin: '+origin)
    elif change == 'symlink':
        other = root / 'other.yaml'; other.write_text(path.read_text()); path.unlink(); path.symlink_to(other)
    elif change == 'missing': env.pop('RLFLOW_REQUEST_TOKEN')
    if change not in ('duplicate', 'symlink'): path.write_text(json.dumps(data))
    with pytest.raises(ClientError): AgentClient(cwd=root, environ=env)


def test_client_entry_never_constructs_store_even_on_error(tmp_path, monkeypatch, capsys):
    from rlflow import cli
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, 'Store', lambda *a, **k: (_ for _ in ()).throw(AssertionError('client constructed a Core Store')))
    assert cli.main(['client', 'skill-path']) == 0
    assert Path(capsys.readouterr().out.strip()).is_file()
    assert cli.main(['client', 'status', '--request', 'request_' + '0' * 64]) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'[' * 1001, b' ' * (256 * 1024 + 1)])
def test_closed_bounded_json(raw):
    with pytest.raises(ClientError): closed_json(raw)


@pytest.mark.parametrize('bad', ['adopted_null', 'private_field', 'missing_hash', 'wrong_id', 'false_success', 'bad_actor', 'wrong_submit_hash', 'wrong_submit_id'])
def test_client_closed_receipts_never_print_false_acceptance(tmp_path, monkeypatch, bad):
    from email.message import Message
    with hosted(tmp_path) as (_, _, proposal, _, env):
        root = config(tmp_path, env['RLFLOW_CONTROL_ORIGIN']); client = AgentClient(cwd=root, environ=env)
        saved = client.submit_goal(proposal, key='original'); corrupted = dict(saved)
        if bad == 'adopted_null': corrupted['status'] = 'ADOPTED'
        elif bad == 'private_field': corrupted['proposal'] = proposal
        elif bad == 'missing_hash': corrupted.pop('request_hash')
        elif bad == 'wrong_id': corrupted['request_id'] = 'request_' + 'a' * 64
        elif bad == 'false_success': corrupted['result'] = {'state': 'DRAFT'}
        elif bad == 'bad_actor': corrupted['submitted_by'] = {'id': 'human', 'kind': 'human'}
        elif bad == 'wrong_submit_hash': corrupted['request_hash'] = 'sha256:' + '0' * 64
        elif bad == 'wrong_submit_id': corrupted['request_id'] = 'request_' + 'a' * 64
        class Response:
            headers = Message()
            headers['Content-Type'] = 'application/json'
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, *a): return json.dumps(corrupted).encode()
        monkeypatch.setattr(client._opener, 'open', lambda *a, **k: Response())
        with pytest.raises(ClientError):
            if bad in ('wrong_submit_hash', 'wrong_submit_id'): client.submit_goal(proposal, key='original')
            else: client.get_report(saved['request_id'])


def test_actual_redirect_refusal_and_ambient_proxy_cannot_receive_token(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302); self.send_header('Location', 'http://127.0.0.1:1/credential_sink'); self.end_headers()
        def log_message(self, *a): pass
    server = HTTPServer(('127.0.0.1', 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        root = config(tmp_path, origin)
        monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1'); monkeypatch.setenv('NO_PROXY', '')
        client = AgentClient(cwd=root, environ={'RLFLOW_CONTROL_ORIGIN': origin, 'RLFLOW_REQUEST_TOKEN': 'synthetic_request_token_not_logged'})
        with pytest.raises(ClientError, match='redirect refused'): client.get_status('request_' + '0' * 64)
        assert len(seen) == 1 and seen[0].endswith('/request_' + '0' * 64)
    finally:
        server.shutdown(); thread.join(3); server.server_close()


def test_special_input_files_fail_without_blocking_or_http(tmp_path):
    fifo = tmp_path / 'input_fifo'; os.mkfifo(fifo)
    with pytest.raises(ClientError): read_regular(fifo, 8192)
    with pytest.raises(ClientError): read_regular('/dev/null', 8192)
    root = config(tmp_path, 'http://127.0.0.1:8765')
    path = root / '.rlflow' / 'project.yaml'; path.unlink(); os.mkfifo(path)
    with pytest.raises(ClientError): AgentClient(cwd=root, environ={'RLFLOW_CONTROL_ORIGIN': 'http://127.0.0.1:8765', 'RLFLOW_REQUEST_TOKEN': 'synthetic_request_token_not_logged'})
