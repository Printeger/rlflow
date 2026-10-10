"""Owned loopback fixture: actual client/inbox/Core DRAFT, never execution."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from rlflow.agent_client import AgentClient
from rlflow.hybrid_agent_requests import AgentRequestService
from rlflow.hybrid_goals import SECTIONS
from rlflow.observation import enable
from rlflow.store import Store
from rlflow.web_api import Project, create_app
from rlflow.web_auth import Principal, Credential
from tests.test_hybrid_control_api import setup, PHRASE


def main():
    root = Path(sys.argv[1]).resolve()
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    store, auth, proposal, _, pair, projects, _ = setup(root, origin=origin)
    for key, credential in tuple(auth.credentials.items()):
        old = credential.principal
        auth.credentials[key] = Credential.create(Principal(old.id, old.kind, old.roles, {'project_fixture','project_other'}), PHRASE)
    other = Store(root / 'other_state'); enable(other, 'project_other', data_mode='fixture')
    projects.append(Project('project_other', str(other.root), 'fixture'))
    service = AgentRequestService(pair.drafts)
    token, _ = auth.issue_request_token(Principal('browser_agent','agent',{'viewer'},{'project_fixture'}), ttl=50)
    target = root / 'target'; (target / '.rlflow').mkdir(parents=True)
    (target / '.rlflow/project.yaml').write_text(json.dumps({'schema_version':'1.0','project_id':'project_fixture','control_origin':origin}))
    client = AgentClient(cwd=target, environ={'RLFLOW_CONTROL_ORIGIN':origin,'RLFLOW_REQUEST_TOKEN':token})
    app = create_app(projects, auth, origin=origin, control_services={'project_fixture':pair},
                     agent_request_services={'project_fixture':service})
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, proxy_headers=False))
    saved = {}
    def controls():
        try:
            for line in sys.stdin:
                command = json.loads(line); op = command['op']
                if op == 'stop': break
                if op == 'submit':
                    p = deepcopy(proposal); p['goal_id'] = command['goal_id']
                    p['global_conditions'][0]['description'] = '<img src=x onerror="window.requestInjected=1"> exact unapproved proposal'
                    value = client.submit_goal(p, key=command['key']); saved[value['request_id']] = value
                elif op == 'report': value = client.get_report(command['request_id'])
                elif op == 'inspect':
                    value = {'version':store.version(),'drafts':len(store.objects(SECTIONS[0])),
                        'tasks':len(store.objects('tasks')),'sessions':len(store.objects('sessions')),
                        'jobs':len(store.objects('jobs')),'other_version':other.version()}
                else: raise ValueError('unknown private fixture operation')
                print(json.dumps(value), flush=True)
        finally: server.should_exit = True
    thread = threading.Thread(target=controls, daemon=True); thread.start()
    print(json.dumps({'origin':origin}), flush=True)
    try: server.run(sockets=[sock])
    finally: sock.close()


if __name__ == '__main__': main()
