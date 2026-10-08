"""Owned local browser fixture. Controls are stdin-only, never HTTP commands."""
import json
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from rlflow.observation import ObservationReader, enable
from rlflow.store import Store, sha
from rlflow import tool_journal, tool_collector
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Credential, Principal


def main():
    root = Path(sys.argv[1]).resolve()
    store = Store(root / "state")
    enable(store, "project_fixture", data_mode="fixture")
    before = dict(path=str(root), head="fixture-not-a-commit", tree_sha256="0" * 64, files={})

    def task(key, description):
        value = dict(id=key, version=1, stage_id="fixture_stage", cycle_id=key, text=description,
                     repo=str(root), baseline=before, status="QUEUED", next_role="Engineer",
                     repair_rounds=0, diagnostic_after_rounds=1, results=[], findings=[], consulted=[],
                     completion=dict.fromkeys(("implementation", "cpu", "real_run", "behavior", "formal"), False))
        store.transact_objects("TASK_CREATED", key, [("tasks", key)], lambda s: s["tasks"].update({key: value}))

    task("initial", 'Fixture task <img src=x onerror="window.injected=1">')
    session = dict(id="fixture_session", role="Engineer", task_id="initial", task_version=1,
                   stage_id="fixture_stage", input_state_version=1, status="RUNNING", directory=str(root),
                   scratch=str(root), limit=1, before=before, identity=None, created=0,
                   compute={"model": "fixture:none"})
    store.transact_objects("FIXTURE_OBSERVED", "initial_session", [("sessions", "fixture_session")],
                           lambda s: s["sessions"].update(fixture_session=session))
    phrase = "synthetic browser fixture passphrase"
    auth = AuthStore([Credential.create(Principal(name, "human", frozenset({"viewer"}), frozenset({project})), phrase)
                      for name, project in (("local", "project_fixture"), ("no_projects", "not_registered"))])
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = create_app([Project("project_fixture", str(store.root), "fixture")], auth, origin=origin,
                     stream_options={"poll": .02, "heartbeat": .15})
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, proxy_headers=False))

    def controls():
        try:
            for line in sys.stdin:
                command = json.loads(line)
                if command["op"] == "stop": break
                if command["op"] == "task": task(command["id"], command.get("text", "Real durable fixture update"))
                elif command["op"] == "expire":
                    with auth._lock: auth._sessions.clear()
                elif command["op"] == "burst":
                    for index in range(command["count"]): task(f'burst_{index}', f'Bounded fixture {index}')
                elif command["op"] == "usage":
                    store.transact_objects("USAGE_OBSERVED",command["id"],[("usage",command["id"])],
                        lambda s:s.setdefault("usage",{}).update({command["id"]:{"status":command["status"],"task_id":"initial"}}))
                elif command['op']=='tool':
                    # Serialized trusted-core fixture for UI routing, NOT a CPU
                    # execution or vendor proof. Real CPU→collector is separately
                    # exercised in tests/test_public_tools.py. No raw tool text.
                    context = dict(schema_version='1.0',session='fixture_session',generation='fixture_generation',
                                   request_sha256='1'*64,candidate_sha256='2'*64)
                    source = tool_collector.source_id(context['session'],context['generation'])
                    registration = dict(schema_version='1.0',kind='CPU_REGISTER',epoch=tool_journal.digest(context),
                                        ordinal=1,previous_sha256='0'*64,command_digest=sha(command['id']),intent_sha256='3'*64,
                                        context=context,launch_witness=dict.fromkeys(('release_sha256','model_release_sha256','ack_sha256'),'4'*64))
                    registration['record_sha256']=tool_journal.digest(registration)
                    fact = dict(schema_version='1.0',kind='CPU_EXEC_RETURN',tool='cpu_exec',context=context,
                                intent_sha256='3'*64,result_sha256='5'*64,state='RETURNED',exit_code=1,timed_out=False,
                                wall_seconds=.125,infrastructure_error=None)
                    receipt = tool_collector._receipt(source,registration)
                    receipt.update(status='COLLECTED',verification='VERIFIED',fact=fact,task_id='initial',validation_version=2,
                                   validation_digest=sha(dict(fact=fact,witness=registration['launch_witness'],context=context,task_id='initial')))
                    key = receipt['id']
                    store.transact_objects('ROLE_TOOL_OBSERVED',command['id'],[('tool_receipts',key)],
                                           lambda s:s.setdefault('tool_receipts',{}).update({key:receipt}))
                else: raise ValueError("unknown fixture control")
                print(json.dumps({"reply": command["op"], "head": ObservationReader(store.root).head()}), flush=True)
        finally:
            server.should_exit = True

    threading.Thread(target=controls, daemon=True).start()
    print(json.dumps({"origin": origin}), flush=True)
    try: server.run(sockets=[sock])
    finally: sock.close()


if __name__ == "__main__": main()
