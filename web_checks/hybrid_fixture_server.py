"""Disposable owned browser fixture; actual Hybrid HTTP services, no execution."""
import json
from copy import deepcopy
from pathlib import Path
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from tests.test_hybrid_control_api import setup
from rlflow.hybrid_goals import SECTIONS as GOALS, head_key
from rlflow.hybrid_authority import SECTIONS as AUTHORITY


def main():
    root = Path(sys.argv[1]).resolve()
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    store, auth, proposal, app, pair, _, _ = setup(root, origin=origin)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, proxy_headers=False))

    def controls():
        try:
            for line in sys.stdin:
                command = json.loads(line)
                extra = {}
                if command['op'] == 'stop':
                    break
                if command['op'] == 'expire':
                    with auth._lock:
                        auth._sessions.clear()
                elif command['op'] == 'unsafe_goal':
                    # Valid server int64, not expressible exactly by JS Number.
                    p = deepcopy(proposal)
                    p['goal_id'] = 'fixture_unsafe_budget'
                    p['budget']['model_input_tokens'] = 9007199254740993
                    token, access = auth.login('operator', 'synthetic HTTP control fixture passphrase')
                    pair.drafts.submit(p, token=token, csrf=access.csrf, origin=origin,
                        idempotency_key='fixture_unsafe_budget', expected_revision=0, expected_state_version=store.version())
                    extra['unsafe_ref'] = head_key(p['project_id'], p['data_mode'], p['goal_id'])
                elif command['op'] != 'inspect':
                    raise ValueError('unknown fixture operation')
                state = store.audit()
                print(json.dumps({'version': state['version'], 'goals': len(state.get(GOALS[0], {})),
                    'approvals': len(state.get(AUTHORITY[0], {})), 'revocations': len(state.get(AUTHORITY[1], {})),
                    'sessions': len(state.get('sessions', {})), 'tasks': len(state.get('tasks', {})), **extra}), flush=True)
        finally:
            server.should_exit = True

    thread = threading.Thread(target=controls, daemon=True)
    thread.start()
    print(json.dumps({'origin': origin, 'proposal': proposal}), flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == '__main__':
    main()
