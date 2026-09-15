"""Single dispatcher; short-lived supervised role sessions, restart reconciliation."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .store import Store, atomic, canonical, sha, Conflict
from .policy import candidate, git, git_bytes, git_diff_bytes, stopped, require_stage, available, STOP_PATHS
from .contracts import validate_result, build_pi_packet, classify_change, ContractError
from .jobs import identity, owns
from .failures import infrastructure_failure
from .role_config import load_role
from .model_policy import select, load_policy

CODE = Path(__file__).resolve().parents[1]
ACTIVE = {"START_INTENT", "RUNNING", "RECONCILE"}


def envelope_candidate(task):
    c = candidate(task["repo"])
    diff = git_diff_bytes(task['repo'], task['baseline']['head'])
    return {"repository": task["repo"], "base_commit": task["baseline"]["head"],
            "commit": c["head"], "diff_sha256": hashlib.sha256(diff).hexdigest()}


def interpretation_matches_stage(interpretation, stage):
    """A PI may narrow authorized roots, but cannot expand or escape them."""
    if not interpretation or interpretation['stage_id'] != stage['id']:
        return False
    roots = interpretation['module_roots']
    if not roots:
        return False
    from pathlib import PurePosixPath
    def valid(value):
        p = PurePosixPath(value)
        return bool(value) and not p.is_absolute() and '..' not in p.parts and '\\' not in value
    if not all(valid(x) for x in roots):
        return False
    return all(any(PurePosixPath(root).is_relative_to(PurePosixPath(allowed))
                   for allowed in stage['module_roots']) for root in roots)


def add_task(store, sid, text, key=None, *, consultation_role=None):
    task_id = task_identity(sid, text, key, consultation_role=consultation_role)
    store.transact("TASK_CREATED", "task:" + task_id,
                   lambda s: create_task(s, store.root, sid, text, key, consultation_role=consultation_role),
                   object_id=task_id)
    return task_id


def task_identity(sid, text, key=None, *, consultation_role=None):
    if consultation_role is not None and consultation_role not in {'Critic','Designer','Scout'}:
        raise Conflict('unsupported consultation role')
    identity_fields = {"stage": sid, "text": text, "key": key or text}
    if consultation_role:
        identity_fields['consultation_role'] = consultation_role
    return "T-" + sha(identity_fields)[:16]


def create_task(s, root, sid, text, key=None, *, consultation_role=None):
    """Create inside the caller's approval transaction; no nested transaction."""
    task_id = task_identity(sid, text, key, consultation_role=consultation_role)
    st = require_stage(s, sid)
    if task_id in s['tasks']:
        return task_id
    if st.get("package_id"):
        raise Conflict("package tasks must match the approved decomposition")
    if any(t["stage_id"] == sid and t["status"] not in {"DONE", "STOPPED", "CONSULTED"} for t in s["tasks"].values()):
        raise Conflict("stage already has an unfinished task")
    if not Path(st["repo"]).resolve().is_relative_to(root / "workspaces"):
        raise Conflict("task repository outside isolated CPU workspaces")
    s["tasks"][task_id] = {"id": task_id, "version": 1, "stage_id": sid, "cycle_id": task_id,
            "text": text, "repo": st["repo"], "baseline": candidate(st["repo"]),
            "status": "QUEUED", "next_role": "PI", "repair_rounds": 0,
            "diagnostic_after_rounds": 3, "results": [], "findings": [], "consulted": [],
            "completion": {"implementation": False, "cpu": False, "real_run": False, "behavior": False, "formal": False}}
    if consultation_role:
        s['tasks'][task_id].update(next_role=consultation_role, mode='consultation', consultation_id='C-'+task_id)
    return task_id


def packet(store, state, task, session):
    st = state["stages"][task["stage_id"]]
    c = envelope_candidate(task)
    expected = {"schema_version": "rlflow/0.2", "role": session["role"], "session_id": session["id"],
                "task_id": task["id"], "task_version": task["version"], "cycle_id": task["cycle_id"],
                "input_state_version": session["input_state_version"]}
    def summarize_candidate(value):
        if not isinstance(value, dict) or "files" not in value:
            return value
        files = value.get("files", {})
        return {**{k: v for k, v in value.items() if k != "files"},
                "file_count": len(files), "files_sha256": sha(files)}
    packet_task = {k: summarize_candidate(v) for k, v in task.items() if k not in {'results', 'requested_actions'}}
    from .evidence import reachable
    related = [{**e,'event_sequence':e.get('event_sequence',state['sessions'].get(e['id'].removeprefix('E-'),{}).get('input_state_version',0))} for e in reachable(state,task).values()]
    from .repairs import resource_stage
    pool = resource_stage(state,task['stage_id'])
    decisions = [d for d in state['decisions'].values() if d.get('task_id') == task['id'] or d.get('package_id') == task.get('package_id') and task.get('package_id')]
    research_root = state.get('research', {}).get(task.get('package_id', task['stage_id']), {})
    research = research_root.get('cycles', {}).get(task['id'], {})
    minimal = {"version": session["input_state_version"], "charter": "CPU engineering only; no real runtime or GPU",
               "permissions": {"scope": st["scope"], "module_roots": st["module_roots"], "categories": st["categories"]},
               "versions": {"candidate": c, "workflow": "0.2"}, "unresolved_findings": task["findings"],
               "evidence": related, "decisions": decisions, "hypotheses": research.get("hypotheses", []),
               "budgets": {"limits": pool["budget"], "remaining": available(pool)}, "stop": stopped(store.root),
               "task": packet_task, "research_state": research, "counterevidence": research.get('counterevidence', []),
               "approvals": [a for a in state['approvals'].values() if a.get('stage_id') == task['stage_id']], "historical": state["historical"].get("summary", {})}
    if session.get('escalation_package'):
        # The specialist gets the unresolved issue and verified evidence, not
        # another copy of every earlier role's full report.
        minimal['task'] = {k:v for k,v in task.items() if k not in {'results','requested_actions','diagnostic','pending_escalation'}}
    if task.get('cold_review') == 'RAW':
        minimal.pop('decisions', None); minimal.pop('hypotheses', None)
        minimal['research_state'] = {'phase': research.get('phase'), 'experiments': research.get('experiments', [])}
        minimal['task'] = {k:v for k,v in packet_task.items() if k not in {'diagnostic','interpretation','evidence_details'}}
        minimal['evidence'] = [e for e in related if e.get('role') not in {'PI','Critic','Designer','Scout'}]
    if task.get('package_id'):
        from .context import project,save
        pt,rs,ds,es,history,index=project(minimal['task'],minimal.get('research_state',{}),minimal.get('decisions',[]),minimal['evidence'])
        # Raw Cold Review never receives hidden PI interpretations through history.
        minimal.update(task=pt,research_state=rs,decisions=ds,evidence=es,counterevidence=rs.get('counterevidence',[]),history_index=index)
        if session.get('directory'):index['read_only_path']=save(session['directory'],history)
        package=state['packages'][task['package_id']]
        minimal['goal']={'id':package['id'],'text':package['spec']['goal'],'decomposition':package['spec'].get('decomposition'),
            'tasks':[{'id':tid,'parent_id':state['tasks'][tid].get('parent_id'),'status':state['tasks'][tid]['status'],
                      'conditions':[c['id'] for c in state['tasks'][tid]['criteria']]} for tid in package['tasks']],
            'experiments':[{'id':x['id'],'seed':x['seed'],'method':x['method'],'observations':x['observations']} for x in package['spec'].get('experiments',[])]}
        if package['spec'].get('parameter_search'):
            from .search import expand
            minimal['goal']['parameter_trials']={trial['id']:assignment for family in package['spec']['parameter_search'] for trial,assignment in expand(family)}
        related=es
    pi = build_pi_packet(minimal)
    prompt = session["role_definition"]["developer_instructions"]
    prompt += "\n\nFrozen orchestration input (role reports never authorize themselves):\n" + canonical(pi).decode()
    prompt += "\nReturn exactly this envelope (payload according to schema); preserve IDs and versions:\n" + canonical(expected).decode()
    prompt += "\nCurrent candidate identity:\n" + canonical(c).decode()
    prompt += "\nCurrently displayed evidence IDs (older authorized IDs are in the read-only evidence index): " + canonical([e['id'] for e in related]).decode()
    prompt += "\nDo not commit; control plane records the final candidate. Use only cpu_exec. Do not install packages. Use python3 standard library unittest for CPU tests. All requested actions must be structured; never dispatch agents or experiments. Report the provided current candidate when you made no changes."
    prompt += "\nAssigned CPU tool permissions: " + canonical({
        "read_candidate": task["repo"], "write_scratch": session["scratch"],
        "write_candidate": task["repo"] if session["role"] == "Engineer" else None,
        "protected_paths": st.get("protected_paths", [])}).decode()
    if task.get('package_id'):
        prompt += '\nApproved criteria are immutable. PI task_interpretation.acceptance_criteria must echo exact condition IDs in order; budget must echo approved limits. Evaluator evidence_coverage must name each proven condition ID. ' + canonical(task['criteria']).decode()
    if task.get('package_id'):
        prompt += '\nHistory omitted from working context remains hash-bound in history_index.read_only_path and evidence/index.json. Inspect it via cpu_exec when prior decisions, negative results or contradictions matter. Never infer success from omission.'
        if state['packages'][task['package_id']]['spec'].get('decomposition'):
            prompt += '\nPI may REQUEST_DECOMPOSITION as its sole action, fields=[JSON string {children:[{id,text,depends_on,condition_ids}]}]. Children inherit all scope, protected paths and the same total budget. Map every immutable parent condition, use sibling IDs for acyclic dependencies, and obey approved max_tasks/max_depth. No new criteria or permissions. After children finish, integrate and independently revalidate the parent goal. A parent can be split once; refine unfinished children if needed.'
        if task.get('research_mode'):
            prompt += '\nFor research choose an unused approved experiment ID. On independent PASS, Evaluator evidence_coverage names proven condition IDs and OBSERVATION JSON binding condition_id/evidence_id/evidence_sha256/explanation to actual raw job evidence. Fresh PI may REQUEST_COMPLETE with fields=[] only after every frozen condition is independently proved at the current candidate and due Cold Review is finished. STOP does not mean goal accomplished.'
    if session["role"] == "PI":
        prompt += "\nInterpret the task against the exact stage scope. If it matches engineering CPU work, decision ENGINEERING_DIAGNOSIS, proposal_required false, structured task_interpretation with explicit acceptance criteria. Any scope/contract change requires proposal_required true. Do not implement."
    if session["role"] == "Engineer":
        prompt += "\nImplement and self-test within the stage scope. Preserve tests' acceptance meaning and CONTRACT.md bytes. Save command stdout/stderr in your scratch directory. If adding files, use git add -N for those files so git diff includes them. Obtain git diff BASE_COMMIT SHA256 after editing and report exact candidate. Include all changed paths and suggested categories; unresolved findings are not waived."
    if session["role"] == "Evaluator":
        prompt += "\nIndependently inspect git diff against base and implementation, add boundary checks in your writable scratch, execute tests, verify acceptance and semantic categories. Candidate is read-only. PASS only at CPU layer with complete evidence. Do not accept based solely on Engineer claims."
    if task.get('integration_review'):
        prompt += '\nThis is parent integration after child completion. Independently test every original parent condition and interactions across children against the final cumulative candidate; child PASS alone cannot close the parent. New findings must bind original conditions.'
    if task.get('mode') == 'consultation':
        prompt += '\nThis is a bounded consultation, not implementation or approval. Read the supplied candidate materials using cpu_exec. Return substantive role output. Consultation ID: '+task['consultation_id']
    if session.get('escalation_package'):
        prompt += '\nBounded escalation package. Focus on this unresolved question; authority is unchanged. Verify the supplied read-only evidence rather than repeating the full project analysis:\n'+canonical(session['escalation_package']).decode()
    prompt += '\nModel escalation is only a request: use REQUEST_MODEL_ESCALATION with fields=[authorized case ID], evidence_ids and a concrete purpose. No case or budget means wait for control-plane resolution; never self-dispatch or treat model escalation as authority.'
    return prompt, expected


def dispatch_one(store, *, allow_paused=False):
    with store.lock('scheduler'):
        snapshot=store.replay()
        if stopped(store.root) or any(se['status'] in ACTIVE for se in snapshot['sessions'].values()):return None
        if snapshot['paused'] and not allow_paused and not snapshot.get('autonomous_tasks'):return None
        pointer=store.root/'runtime/current-release.json'
        before=pointer.read_bytes() if pointer.exists() else None
        _schedule_pending(store)
        if (pointer.read_bytes() if pointer.exists() else None)!=before:return None
        with store.lock('dispatch-release'):
            return _dispatch_one(store, allow_paused=allow_paused)


def _dispatch_one(store, *, allow_paused=False):
    """Dispatch once; an explicit operator step may run while the daemon is paused.

    STOP, active-session, candidate, approval and budget gates still apply.
    Daemons never pass allow_paused.
    """
    dispatch_generation = daemon_generation()
    state = store.replay()
    autonomous = state.get('autonomous_tasks', [])
    if (state["paused"] and not allow_paused and not autonomous) or stopped(store.root) or any(s["status"] in ACTIVE for s in state["sessions"].values()):
        return None
    queued = [t for t in state["tasks"].values() if t["status"] == "QUEUED"]
    if state['paused'] and not allow_paused:
        queued = [t for t in queued if t['id'] in autonomous]
    queued = [t for t in queued if not t.get("last_failure", {}).get("blocked", False)]
    if not queued:
        return None
    from .isolation import require_doctor
    require_doctor(store.root)
    from .packages import runnable
    queued = [t for t in queued if runnable(state, t)]
    if not queued:
        return None
    task = sorted(queued, key=lambda t: (t.get('package_id', ''), t.get('order', 0), t['id']))[0]
    st = require_stage(state, task["stage_id"])
    current = candidate(task["repo"])
    expected_candidate = task.get("accepted_candidate", task["baseline"])
    if current != expected_candidate:
        store.transact("CANDIDATE_DRIFT", "drift:" + task["id"] + ":" + str(task["version"]),
                       lambda s: s["tasks"][task["id"]].update(status="CONTRACT_DECISION", last_error="candidate changed outside accepted role"), expected=state["version"])
        return None
    from .repairs import resource_stage
    pool = resource_stage(state, task['stage_id'])
    balance = available(pool)
    if balance["role_calls"] <= 0 or balance["wall_seconds"] < 1:
        store.transact("BUDGET_EXHAUSTED", "budget:" + task["id"] + ":" + str(task["version"]),
                       lambda s: s["tasks"][task["id"]].update(status="BUDGET_EXHAUSTED"), expected=state["version"])
        return None
    definition = load_role(task['next_role'])
    try:
        if task.get('pending_escalation'):
            from .escalations import validate_case
            pending = task['pending_escalation']
            case,compute,source = validate_case(store,state,pending['case_id'],pending['source_session'])
            if compute != pending['choice'] or case['role'] != task['next_role']:
                raise Conflict('queued model choice changed')
        else:
            compute = select(pool, task['next_role'])
    except Conflict as exc:
        message = str(exc)
        store.transact('COMPUTE_BLOCKED', 'compute-block:'+task['id']+':'+str(task['version']),
                       lambda s: s['tasks'][task['id']].update(status='COMPUTE_BLOCKED', last_error=message), expected=state['version'])
        return None
    sid = "S-" + uuid.uuid4().hex[:16]
    directory = store.root / "roles" / sid
    directory.mkdir(parents=True)
    scratch = directory / "scratch"
    scratch.mkdir()
    session = {"id": sid, "role": task["next_role"], "task_id": task["id"], "task_version": task["version"],
               "stage_id": task["stage_id"], "input_state_version": state["version"] + 1,
               "status": "START_INTENT", "directory": str(directory), "scratch": str(scratch),
               "limit": min(st["per_call_seconds"], balance["wall_seconds"]), "before": candidate(task["repo"]),
               "identity": None, "created": time.time(), "compute": compute, "role_definition": definition, "explicit_step": allow_paused}
    if task.get('pending_escalation'):
        from .escalations import materialize
        session['escalation_package'] = materialize(directory,task['pending_escalation'])
    def reserve(s):
        if (s["paused"] and not allow_paused and task['id'] not in s.get('autonomous_tasks', [])) or stopped(store.root):
            raise Conflict("dispatch stopped")
        require_stage(s, task["stage_id"])
        stage = resource_stage(s, task["stage_id"])
        if any(x['status'] in ACTIVE for x in s['sessions'].values()):
            raise Conflict('another dispatcher owns an active session')
        from .accounting import reserve as reserve_model
        reserve_model(stage, session)
        if task.get('pending_escalation'):
            s['decisions'][task['pending_escalation']['case_id']]['consumed_by'] = sid
        s["sessions"][sid] = session
        s["tasks"][task["id"]]["status"] = "RUNNING"
        return {"reservation": session["limit"], "role_calls": 1}
    reserved = store.transact("ROLE_START_INTENT", sid + ":reserve", reserve, expected=state["version"], object_id=sid)
    try:
        from .evidence import materialize
        materials = materialize(store, reserved, reserved['tasks'][task['id']], directory)
        from .evidence import recovery_material
        recovery=recovery_material(store,reserved,reserved['tasks'][task['id']],directory)
        prompt, expected = packet(store, reserved, reserved["tasks"][task["id"]], session)
        if recovery:prompt+='\nRead-only recovery context: '+canonical(recovery).decode()
        if materials:
            atomic(directory/'evidence/index.json',canonical(materials))
            prompt += '\nRead-only evidence index: '+str(directory/'evidence/index.json')+' ('+str(len(materials))+' objects; SHA256 '+sha(materials)+')'
        import tiktoken
        if len(tiktoken.get_encoding('cl100k_base').encode(prompt))>15000:raise ContractError('complete role input exceeds 15000 tokens; split or request bounded evidence')
        atomic(directory / "prompt.txt", prompt.encode())
        atomic(directory / "expected.json", canonical(expected))
        schema_path = directory / 'schema.json'
        atomic(schema_path, (CODE / 'schemas' / definition['schema']).read_bytes())
        request = {**session, 'recovery_protocol':1, "root": str(store.root), "repo": task["repo"], "prompt": prompt,
                   "schema": str(schema_path),
                   "write_roots": [str((Path(task["repo"]) / root).resolve()) for root in st["module_roots"]],
                   "cpu_runtime": st.get("cpu_runtime"), "command_seconds": st.get("command_seconds", 120)}
        atomic(directory / "request.json", canonical(request))
    except Exception as exc:
        _settle_prelaunch_failure(store, sid, f"{type(exc).__name__}: {exc}")
        raise
    from .releases import freeze
    frozen = freeze(store.root / 'session_releases')
    if daemon_generation() != dispatch_generation:
        raise Conflict('control source changed during dispatch preparation')
    with (directory / "supervisor.log").open("ab") as log:
        child = subprocess.Popen([sys.executable, "-m", "rlflow.worker", str(directory / "request.json")],
                                 cwd=frozen, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    ident = identity(child.pid)
    store.transact("ROLE_IDENTITY", sid + ":identity", lambda s: s["sessions"][sid].update(identity=ident, status="RUNNING"), object_id=sid)
    # Child waits for this durable release. Unknown launches never receive a second release.
    latest = store.replay()
    try:
        require_stage(latest, task['stage_id'])
        if (stopped(store.root) or candidate(task['repo']) != session['before']
                or latest['tasks'][task['id']]['version'] != session['task_version']
                or not runnable(latest,latest['tasks'][task['id']])):
            raise Conflict('release boundary changed')
        atomic(directory / "release", canonical({"session": sid, "identity": ident, "control_release": frozen.name}))
    except Conflict:
        atomic(directory / "cancel", b"authorization/STOP/candidate changed before release")
    return sid


def _settle_prelaunch_failure(store, sid, error):
    """Close a charged role intent only when no worker request was materialized."""
    state = store.replay()
    session = state["sessions"].get(sid)
    if not session or session["status"] not in ACTIVE or session.get("identity") is not None:
        return False
    directory = Path(session["directory"])
    if (directory / "request.json").exists():
        return False
    atomic(directory / "validation.json", canonical({
        "error": error, "accounting": "worker not launched; model reservation released"
    }))
    def settle(s):
        se = s["sessions"][sid]
        from .repairs import resource_stage
        stage = resource_stage(s, se["stage_id"])
        from .accounting import settle as settle_model
        settle_model(stage, se, {'elapsed_seconds': 0, 'model_usage': {'state': 'NOT_STARTED'}})
        se.update(status="REJECTED", error=error, prelaunch_failure=True)
        task = s["tasks"][se["task_id"]]
        if task["version"] == se["task_version"]:
            task["version"] += 1
            task.update(status="QUEUED", last_error=error,
                        last_failure={"kind": "PRELAUNCH", "blocked": True, "repeated": False})
    store.transact("ROLE_PRELAUNCH_REJECTED", sid + ":prelaunch", settle,
                   object_id=sid, expected=state["version"])
    return True


def _classification(task, engineer, evaluation, stage):
    actual = candidate(task["repo"])
    base = task["baseline"]["files"]
    changed = {p for p in set(base) | set(actual["files"]) if base.get(p) != actual["files"].get(p)}
    declared = {c["path"]: c for c in engineer["payload"]["changes"]}
    if changed != set(declared):
        return {"status": "UNRESOLVED", "reasons": ["Engineer change list does not match actual candidate files"], "categories": []}
    ep = engineer["payload"]
    vp = evaluation["payload"]
    # Role schemas use TEST as a descriptive label.  A test that is inside the
    # approved roots and directly supports the fix carries the stage's
    # ENGINEERING_FIX category; this normalization does not add authority.
    normalize = lambda value: "ENGINEERING_FIX" if value == "TEST" else value
    reviewed = {normalize(value) for value in vp["suggested_categories"]}
    return classify_change([{"path": str(Path(task["repo"]) / p),
                            "categories": [normalize(declared[p]["suggested_category"])],
                            "review_categories": ([normalize(declared[p]["suggested_category"])]
                                                  if normalize(declared[p]["suggested_category"]) in reviewed else []),
                            "contract_ref": task["stage_id"]} for p in changed],
                           stage["categories"], module_roots=[str(Path(task["repo"]) / p) for p in stage["module_roots"]],
                           protected_paths=[str(Path(task["repo"]) / p) for p in stage.get("protected_paths", [])], candidate=actual,
                           diff_sha256=envelope_candidate(task)["diff_sha256"])


def accept_result(store, sid):
    state = store.replay()
    session = state["sessions"][sid]
    if session["status"] not in ACTIVE:
        return
    d = Path(session["directory"])
    # Invalid completion accounting is an uncertain launch, not a zero-cost failure.
    try:
        receipt = json.loads((d / "receipt.json").read_text())
        elapsed = receipt["elapsed_seconds"]
        if (receipt["session_id"] != sid or type(receipt["exit_code"]) is not int
                or type(elapsed) not in (int, float) or not 0 <= elapsed < float("inf")):
            raise ValueError("invalid receipt identity, exit code or elapsed time")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        message = str(exc)
        atomic(d / "validation.json", canonical({"error": message, "accounting": "unknown; reservation retained"}))
        store.transact("ROLE_RECEIPT_UNCERTAIN", sid + ":bad-receipt",
                       lambda s: s["sessions"][sid].update(status="RECONCILE", error=message), object_id=sid)
        return
    task = state["tasks"][session["task_id"]]
    result, error, contract_error = None, None, False
    current_candidate = None
    test_artifacts = []
    command_audit = None
    infrastructure_error = infrastructure_failure(d)
    try:
        stage = require_stage(state, session["stage_id"])
    except Conflict as exc:
        error, contract_error = str(exc), True
    try:
        current_candidate = candidate(task["repo"])
        stage = state["stages"][session["stage_id"]]
        for protected in stage.get("protected_paths", []):
            baseline = task["baseline"]["files"]
            names = set(baseline) | set(current_candidate["files"])
            if any((name == protected or name.startswith(protected.rstrip("/") + "/"))
                   and baseline.get(name) != current_candidate["files"].get(name) for name in names):
                contract_error = True
                raise ContractError("frozen contract/protected candidate path changed: " + protected)
        if current_candidate["head"] != task["baseline"]["head"]:
            contract_error = True
            raise ContractError("frozen candidate commit changed")
        if session["role"] != "Engineer" and current_candidate != session["before"]:
            contract_error = True
            raise ContractError("read-only candidate changed during role")
        if infrastructure_error:
            raise ContractError("infrastructure failure: " + infrastructure_error)
        if receipt["exit_code"] != 0:
            raise ContractError("role failed: " + str(receipt))
        result = json.loads((d / "result.json").read_text())
        expected = json.loads((d / "expected.json").read_text())
        from .evidence import reachable
        validate_result(result, expected, reachable(state,task))
        if task["version"] != session["task_version"] or task["status"] != "RUNNING":
            raise ContractError("stale task result")
        if result["candidate"] != envelope_candidate(task):
            raise ContractError("candidate or diff hash mismatch")
        import copy
        from .research import requests, route
        shadow = copy.deepcopy(state); shadow_task = shadow['tasks'][task['id']]
        requests(shadow, shadow_task, session, result)
        route(shadow, shadow_task, session, result)
        escalations = [a for a in result['requested_actions'] if a['action']=='REQUEST_MODEL_ESCALATION']
        if len(escalations)>1 or any(len(a['fields'])!=1 or not a['purpose'].strip() for a in escalations):
            raise ContractError('at most one concrete model escalation request is allowed')
        if task.get('mode') == 'consultation':
            payload = result['payload']
            if session['role'] == 'Scout' and (payload['consultation_id'] != task['consultation_id'] or not payload['cards']):
                raise ContractError('Scout requires matching consultation ID and technical cards')
            if session['role'] == 'Critic' and not payload['hypotheses']:
                raise ContractError('Critic requires at least one discriminating hypothesis')
            if session['role'] == 'Designer' and (not payload['question'].strip() or not payload['decision_rules'] or not payload['stop_conditions']):
                raise ContractError('Designer requires a question, decision rules and stop conditions')
        if task.get('package_id') and session['role'] == 'PI':
            interpretation = result['payload']['task_interpretation']
            if interpretation and (interpretation['acceptance_criteria'] != [c['id'] for c in task['criteria']]
                                   or interpretation['budget'] != stage['budget']):
                contract_error = True
                raise ContractError('PI cannot change approved acceptance conditions or budget')
        if task.get('package_id') and session['role'] == 'Evaluator':
            import copy
            from .progress import review, verify_observations
            shadow = copy.deepcopy(state)
            verify_observations(shadow, shadow['tasks'][task['id']], session, result['payload'])
            review(shadow, shadow['tasks'][task['id']], result['payload'])
        if session["role"] == "Engineer":
            if not result["payload"]["self_tests"] or any(t["exit_code"] != 0 for t in result["payload"]["self_tests"]):
                raise ContractError("Engineer has no passing self-tests")
            for test in result["payload"]["self_tests"]:
                if not test["argv"]:
                    raise ContractError("self-test command is empty")
                for field in ("stdout_path", "stderr_path"):
                    ref = Path(test[field])
                    if not ref.is_absolute():
                        ref = Path(session["scratch"]) / ref
                    resolved = ref.resolve(strict=True)
                    if not resolved.is_relative_to(Path(session["scratch"]).resolve()) or ref.is_symlink() or not resolved.is_file():
                        raise ContractError("self-test evidence must be a regular file within assigned scratch")
                    test_artifacts.append({"field": field, "path": str(resolved),
                                           "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()})
        if session["role"] == "Evaluator" or task.get('mode') == 'consultation':
            audit_path = d / "result.json.commands.jsonl"
            raw_audit = audit_path.read_bytes()
            commands = [json.loads(line) for line in raw_audit.splitlines() if line.strip()]
            if not any(isinstance(cmd, dict) and cmd.get("command") and cmd.get("argv")
                       and type(cmd.get("exit_code")) is int and cmd["exit_code"] == 0
                       and not cmd.get("timed_out", False) for cmd in commands):
                raise ContractError("Evaluator needs a successful actual CPU command audit")
            command_audit = {"path": str(audit_path), "sha256": hashlib.sha256(raw_audit).hexdigest(),
                             "commands": len(commands)}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        error = str(exc)
    classification = None
    if not error and session["role"] == "Evaluator" and result["payload"]["verdict"] == "PASS" and not task.get("research_job") and not task.get("cold_review"):
        if result["payload"]["conclusion_layer"] != "CPU":
            error = "MVP accepts CPU evidence only"
        else:
            eng = next((x for x in reversed(task["results"]) if x["role"] == "Engineer"), None)
            classification = _classification(task, eng, result, state["stages"][task["stage_id"]]) if eng else {"status": "UNRESOLVED"}
    failure = None
    if error:
        kind = "CONTRACT" if contract_error else ("INFRASTRUCTURE" if infrastructure_error else "ROLE_OUTPUT")
        normalized = error.replace(str(d), "<session>").replace(sid, "<session-id>")
        fingerprint = sha({"kind": kind, "cause": infrastructure_error or ("INVALID_ROLE_RESULT" if kind == "ROLE_OUTPUT" else normalized.splitlines()[0]),
                           "role": session["role"], "scope": task.get("package_id", task["stage_id"])})
        previous = task.get("last_failure", {})
        repeated = previous.get("fingerprint") == fingerprint
        failure = {"kind": kind, "code": infrastructure_error, "fingerprint": fingerprint,
                   "repeated": repeated, "blocked": bool(contract_error or infrastructure_error or repeated or receipt["exit_code"] != 0)}
    artifact = {"receipt": receipt, "result_sha256": hashlib.sha256((d / "result.json").read_bytes()).hexdigest() if (d / "result.json").exists() else None, "error": error, "classification": classification, "self_test_artifacts": test_artifacts, "command_audit": command_audit, "failure": failure}
    atomic(d / "validation.json", canonical(artifact))
    def settle(s):
        se = s["sessions"][sid]
        from .repairs import resource_stage
        stage = resource_stage(s, se["stage_id"])
        from .accounting import settle as settle_model
        settle_model(stage, se, receipt)
        se.update(status="REJECTED" if error else "ACCEPTED", receipt=receipt, error=error)
        t = s["tasks"][se["task_id"]]
        if t["version"] != se["task_version"]:
            return {"stale": True, "error": error}
        t["version"] += 1
        if error:
            status = ("CONTRACT_DECISION" if contract_error else "INFRASTRUCTURE_ERROR" if infrastructure_error
                      else "REPEATED_BLOCKER" if failure["repeated"] else "ROLE_ERROR" if receipt["exit_code"] != 0 else "QUEUED")
            t.update(status=status, last_error=error, last_failure=failure)
            if t.get('package_id') and failure['repeated'] and not contract_error and not infrastructure_error and receipt['exit_code']==0:
                if not t.get('invalid_output_diagnostic'):
                    t.update(status='QUEUED',next_role='Critic',invalid_output_diagnostic=True,continuation_requires_evidence=True)
                    t['last_failure']['blocked']=False
                else:
                    t.update(status='CONTRACT_DECISION',last_error='diagnostic route still cannot produce a valid result; no automatic repetition')
            recovered=receipt.get('recovery',{})
            if receipt.get('interrupted_and_reclaimed') or recovered.get('owner_dead') and not recovered.get('child_alive'):
                if receipt.get('model_usage',{}).get('state') in {'USED','NOT_STARTED'} and not contract_error:
                    t.update(status='QUEUED',next_role=se['role'],recovery_source=sid)
                    t['last_failure']['blocked']=False
                else:t.update(status='RECONCILE',last_error='model use unknown after recovery; reservation retained')
            if infrastructure_error:
                from .repairs import register_in
                t['infrastructure_repair'] = register_in(s, se, failure)
            if not contract_error and session["role"] == "Engineer" and current_candidate:
                t["accepted_candidate"] = current_candidate
            return artifact
        require_stage(s, se["stage_id"])
        t.pop("last_failure", None)
        t.pop('pending_escalation',None)
        t["accepted_candidate"] = current_candidate
        eid = "E-" + sid
        s["evidence"][eid] = {"id": eid, "role": se["role"], "path": str(d), "sha256": sha(result),
                              "scope": "CPU", "accepted": True, "task_id": t["id"], "package_id": t.get("package_id")}
        t["results"].append(result)
        t["status"] = "QUEUED"
        payload = result["payload"]
        if any(a['action']=='REQUEST_MODEL_ESCALATION' for a in result['requested_actions']):
            t.update(status='ESCALATION_PENDING',next_role=se['role'],requested_actions=result['requested_actions'])
            return artifact
        if t.get('mode') == 'consultation':
            t.update(status='CONSULTED', requested_actions=result['requested_actions'])
            return artifact
        from .research import route, requests
        if se['role'] == 'Evaluator' and t.get('package_id'):
            from .progress import verify_observations
            verify_observations(s, t, se, payload)
        if se['role'] == 'PI':
            s['decisions']['D-' + sid] = {'id':'D-' + sid, 'task_id':t['id'], 'package_id':t.get('package_id'),
                'event_sequence':s['version']+1,'session_id':sid,'payload':payload,'counterevidence':payload['counterevidence']}
        if route(s, t, se, result):
            requests(s, t, se, result)
            return artifact
        if se["role"] == "PI":
            interpretation = payload["task_interpretation"]
            s['decisions']['D-' + sid] = {'id': 'D-' + sid, 'task_id': t['id'], 'package_id': t.get('package_id'),
                'event_sequence': s['version'] + 1, 'session_id': sid, 'payload': payload, 'counterevidence': payload['counterevidence']}
            from .progress import continuation
            if not continuation(s, t, payload) and payload['decision'] != 'STOP':
                t.update(status='REPEATED_BLOCKER', last_error='Fresh PI continuation lacks verified new information or discriminating procedure')
                return artifact
            if payload["proposal_required"] or payload["decision"] in {"METHOD_REVIEW", "EVALUATION_REVIEW", "PARAMETER_SEARCH"}:
                t.update(status="CONTRACT_DECISION", proposal_request=payload)
            elif payload["decision"] == "STOP":
                t["status"] = "STOPPED"
            elif interpretation_matches_stage(interpretation, s['stages'][t['stage_id']]):
                t.update(next_role="Engineer", interpretation=interpretation)
            else:
                t.update(status="CONTRACT_DECISION", last_error="task interpretation does not match stage")
        elif se["role"] == "Engineer":
            t["completion"]["implementation"] = True
            t["next_role"] = "Evaluator"
        elif se["role"] == "Evaluator":
            from .progress import review
            repeated_finding = review(s, t, payload)
            t["findings"] = payload["findings"]
            if payload["verdict"] == "PASS" and classification and classification["status"] == "AUTHORIZED":
                t["completion"]["cpu"] = True
                t.update(status="DONE", classification=classification, candidate=candidate(t["repo"]))
                if t.get('package_id'):
                    from .packages import cpu_complete
                    cpu_complete(s, t, eid, current_candidate)
                else:
                    s["stages"][se["stage_id"]]["status"] = "HOLD"
                s["autonomous_tasks"] = [task_id for task_id in s.get("autonomous_tasks", [])
                                         if task_id != t["id"]]
            elif payload["verdict"] == "PASS" or any(f["category"] == "CONTRACT_DECISION" for f in payload["findings"]):
                t.update(status="CONTRACT_DECISION", classification=classification)
            else:
                t["repair_rounds"] += 1
                t["next_role"] = "Critic" if repeated_finding or t["repair_rounds"] % t["diagnostic_after_rounds"] == 0 else "Engineer"
        elif se["role"] == "Critic":
            t.update(next_role="PI", diagnostic=payload)
        elif se["role"] in {"Designer", "Scout"}:
            t.update(next_role="PI")
        requests(s, t, se, result)
        # Requests are data. Only explicitly supported evidence requests can be served here;
        # other research requests await deterministic contract routing, never shell dispatch.
        if result["requested_actions"]:
            t["requested_actions"] = result["requested_actions"]
        return artifact
    def settle_and_refresh(s):
        detail = settle(s)
        t = s['tasks'][session['task_id']]
        if t.get('package_id'):
            from .packages import refresh
            refresh(s,t['package_id'])
        return detail
    store.transact("ROLE_RESULT_REJECTED" if error else "ROLE_RESULT_ACCEPTED", sid + ":settle", settle_and_refresh, object_id=sid, expected=state["version"])
    if not error:
        for request in result['requested_actions']:
            if request['action']=='REQUEST_REVIEW' and request['fields']==['Scout']:
                from .literature import retrieve
                try: retrieve(store, task['id'], request['purpose'])
                except (Conflict, OSError) as exc:
                    message=str(exc)
                    store.transact('SCOUT_SOURCE_UNAVAILABLE',sid+':scout-source',lambda s:s['tasks'][task['id']].update(status='CONTRACT_DECISION',last_error=message),object_id=sid)
            if request['action']=='REQUEST_EVIDENCE_DETAIL':
                from .evidence import detail
                detail(store, sid, request)
            if request['action']=='REQUEST_MODEL_ESCALATION':
                from .escalations import queue
                try:
                    queue(store,request['fields'][0],source_id=sid)
                except (Conflict,KeyError,OSError) as exc:
                    message=str(exc)
                    store.transact('MODEL_ESCALATION_PENDING',sid+':escalation-pending',
                                   lambda s:s['tasks'][session['task_id']].update(last_error=message),object_id=sid)
    if not error and session['role']=='Evaluator':
        latest=store.replay();finished=latest['tasks'][session['task_id']]
        if finished.get('repair_id') and finished['completion']['cpu']:
            from .repairs import verify_repair
            engineer=next(r['session_id'] for r in reversed(finished['results']) if r['role']=='Engineer')
            verify_repair(store,finished['repair_id'],engineer,sid)
    if not error and session["role"] == "Engineer":
        diff = git_diff_bytes(task['repo'], task['baseline']['head'])
        atomic(d / "candidate.diff", diff)


def reconsider_result(store, sid):
    """Revalidate a saved Evaluator result after a narrow classifier repair.

    Reconsideration is allowed only for the immediately rejected result whose
    sole blocker was a CPU transport classification.  It never reserves or
    charges another role call and closes the autonomous stage on CPU PASS.
    """
    state = store.replay()
    session = state["sessions"].get(sid)
    if not session:
        raise Conflict("unknown session")
    if session["status"] == "ACCEPTED":
        return state
    if session["status"] != "REJECTED" or session["role"] != "Evaluator":
        raise Conflict("only a rejected Evaluator result can be reconsidered")
    task = state["tasks"][session["task_id"]]
    failure = task.get("last_failure", {})
    if (task["status"] != "INFRASTRUCTURE_ERROR"
            or task["version"] != session["task_version"] + 1
            or failure.get("code") != "CPU_EXEC_TRANSPORT_ERROR"):
        raise Conflict("task is not at the exact reconsiderable infrastructure failure")
    stage = require_stage(state, session["stage_id"])
    directory = Path(session["directory"])
    if infrastructure_failure(directory) is not None:
        raise Conflict("trusted events still show an infrastructure failure")

    try:
        receipt = json.loads((directory / "receipt.json").read_text())
        result_raw = (directory / "result.json").read_bytes()
        result = json.loads(result_raw)
        expected = json.loads((directory / "expected.json").read_text())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise Conflict("saved result is incomplete: " + str(exc)) from exc
    elapsed = receipt.get("elapsed_seconds")
    if (receipt.get("session_id") != sid or receipt.get("exit_code") != 0
            or type(elapsed) not in (int, float) or not 0 <= elapsed < float("inf")):
        raise Conflict("saved receipt is not a successful exact-session receipt")
    validate_result(result, expected, state["evidence"])
    current = candidate(task["repo"])
    if current != session["before"] or current["head"] != task["baseline"]["head"]:
        raise Conflict("candidate changed after the rejected read-only evaluation")
    baseline = task["baseline"]["files"]
    names = set(baseline) | set(current["files"])
    for protected in stage.get("protected_paths", []):
        if any((name == protected or name.startswith(protected.rstrip("/") + "/"))
               and baseline.get(name) != current["files"].get(name) for name in names):
            raise Conflict("frozen contract/protected candidate path changed: " + protected)
    if result["candidate"] != envelope_candidate(task):
        raise Conflict("saved result candidate or diff hash mismatch")
    payload = result["payload"]
    if (payload["verdict"] != "PASS" or payload["conclusion_layer"] != "CPU"
            or payload["missing_evidence"]):
        raise Conflict("saved result is not a complete CPU PASS")

    audit_path = directory / "result.json.commands.jsonl"
    try:
        raw_audit = audit_path.read_bytes()
        commands = [json.loads(line) for line in raw_audit.splitlines() if line.strip()]
    except (ValueError, OSError, TypeError) as exc:
        raise Conflict("saved command audit is invalid: " + str(exc)) from exc
    if not any(isinstance(command, dict) and command.get("command") and command.get("argv")
               and type(command.get("exit_code")) is int and command["exit_code"] == 0
               and not command.get("timed_out", False) for command in commands):
        raise Conflict("saved Evaluator result has no successful CPU command audit")
    engineer = next((item for item in reversed(task["results"]) if item["role"] == "Engineer"), None)
    classification = _classification(task, engineer, result, stage) if engineer else {"status": "UNRESOLVED"}
    if classification.get("status") != "AUTHORIZED":
        raise Conflict("saved PASS does not classify as authorized engineering work")

    original_validation = (directory / "validation.json").read_bytes()
    artifact = {
        "receipt": receipt,
        "result_sha256": hashlib.sha256(result_raw).hexdigest(),
        "error": None,
        "classification": classification,
        "self_test_artifacts": [],
        "command_audit": {"path": str(audit_path),
                          "sha256": hashlib.sha256(raw_audit).hexdigest(),
                          "commands": len(commands)},
        "failure": None,
        "reconsideration": {
            "original_validation_sha256": hashlib.sha256(original_validation).hexdigest(),
            "reason": "role timeout argument rejection is not an infrastructure failure",
            "accounting": "unchanged; the original role call and elapsed seconds remain charged",
        },
    }

    def settle(saved):
        saved_session = saved["sessions"][sid]
        saved_task = saved["tasks"][saved_session["task_id"]]
        saved_stage = saved["stages"][saved_session["stage_id"]]
        if (saved_session["status"] != "REJECTED"
                or saved_task["version"] != saved_session["task_version"] + 1
                or saved_task.get("last_failure", {}).get("code") != "CPU_EXEC_TRANSPORT_ERROR"):
            raise Conflict("reconsideration target changed")
        saved_session.update(status="ACCEPTED", error=None)
        saved_task["version"] += 1
        saved_task.pop("last_failure", None)
        saved_task.pop("last_error", None)
        saved_task["accepted_candidate"] = current
        evidence_id = "E-" + sid
        saved["evidence"][evidence_id] = {
            "id": evidence_id, "role": "Evaluator", "path": str(directory),
            "sha256": sha(result), "scope": "CPU", "accepted": True,
        }
        saved_task["results"].append(result)
        saved_task["findings"] = payload["findings"]
        saved_task["completion"]["cpu"] = True
        saved_task.update(status="DONE", classification=classification,
                          candidate=current)
        saved_stage["status"] = "HOLD"
        saved["autonomous_tasks"] = [task_id for task_id in saved.get("autonomous_tasks", [])
                                     if task_id != saved_task["id"]]
        return artifact

    final = store.transact("ROLE_RESULT_RECONSIDERED", sid + ":reconsider", settle,
                           object_id=sid, expected=state["version"])
    atomic(store.root / "analyses" / sid / ("reconsider-" + sha(artifact) + ".json"), canonical(artifact))
    return final


def _schedule_pending(store):
    from .repairs import prepare, promote
    for rid, repair in store.replay().get('repairs', {}).items():
        state=store.replay();package=state.get('packages',{}).get(repair['stage_id'])
        if not package or package['paused'] or package['status']!='ACTIVE':continue
        if repair['status']=='NEEDS_ISOLATED_CANDIDATE':
            prepare(store,rid)
        elif repair['status']=='VERIFIED_AWAITING_RELEASE':
            promote(store,rid)
    from . import experiments
    for task in store.replay()['tasks'].values():
        if task['status']=='WAITING_EXPERIMENT':
            from .packages import runnable
            if not runnable(store.replay(),task):continue
            snapshot=store.replay()
            specs=[p['content']['spec'] for p in snapshot['proposals'].values() if p['content'].get('scope')=='EXPERIMENT']
            specs+=snapshot.get('packages',{}).get(task.get('package_id'),{}).get('spec',{}).get('experiments',[])
            for specification in specs:
                if specification['id']==task.get('experiment_request') and specification['stage_id']==task['stage_id']:
                    try: experiments.submit(store, specification)
                    except Conflict as exc:
                        reason=str(exc);current=store.replay()['tasks'][task['id']]
                        if current.get('last_error')!=reason:
                            store.transact('EXPERIMENT_WAIT_REASON','wait:'+task['id']+':'+str(current['version'])+':'+sha(reason),
                                lambda s:s['tasks'][task['id']].update(last_error=reason),object_id=task['id'])


def reconcile(store):
    from .releases import reconcile_pointer
    reconcile_pointer(store)
    from . import experiments
    for jid, job in store.replay()['jobs'].items():
        if job.get('spec',{}).get('backend') in {'real','runner_cpu'}:
            observed=experiments.reconcile(store,jid)
            if observed['status'] in {'SUCCEEDED','FAILED','STOPPED'}:
                evidence=experiments.collect(store,jid)
                def attach(s):
                    for task in s['tasks'].values():
                        if task.get('experiment_request')==job['spec']['id'] and task['stage_id']==job['stage'] and task['status']=='WAITING_EXPERIMENT':
                            task.update(research_job=jid,status='QUEUED',next_role='Evaluator')
                            s['evidence'][evidence['id']].update(task_id=task['id'],package_id=task.get('package_id'))
                store.transact('RESEARCH_JOB_ATTACHED',jid+':attach',attach,object_id=jid)
    for sid, session in store.replay()["sessions"].items():
        if session["status"] not in ACTIVE:
            continue
        d = Path(session["directory"])
        if not owns(session.get('identity')) and not (d/'receipt.json').exists() and (d/'lifeguard-request.json').exists():
            from .lifeguard import reclaim
            ready=json.loads((d/'lifeguard-ready.json').read_text()) if (d/'lifeguard-ready.json').exists() else {}
            if not owns(ready.get('identity')):
                with store.lock('recover-'+sid):
                    if not (d/'receipt.json').exists():reclaim(json.loads((d/'lifeguard-request.json').read_text()))
        if (d / "receipt.json").exists():
            accept_result(store, sid)
        elif (session["status"] == "RECONCILE" and session.get("identity") is None
              and not (d / "request.json").exists()
              and time.time() - session.get("created", time.time()) >= 5):
            _settle_prelaunch_failure(store, sid, "dispatcher failed before worker request")
        elif owns(session.get("identity")):
            continue
        elif session["status"] != "RECONCILE":
            store.transact("ROLE_RECONCILE_REQUIRED", sid + ":uncertain",
                           lambda s, sid=sid: s["sessions"][sid].update(status="RECONCILE"), object_id=sid)
    return store.replay()


def daemon(root):
    store = Store(root)
    with store.lock("daemon", nonblocking=True):
        atomic(store.root / "runtime/daemon.json", canonical(identity(os.getpid())))
        generation = daemon_generation()
        atomic(store.root/'runtime/daemon-code.json',canonical({'generation':generation,'identity':identity(os.getpid())}))
        while True:
            try:
                if daemon_generation() != generation:
                    print('Control code changed; daemon exits without dispatching cached code',flush=True)
                    return
                reconcile(store)
                pointer=store.root/'runtime/current-release.json'
                if pointer.exists() and Path(json.loads(pointer.read_text())['path']).resolve()!=CODE:
                    from .releases import handoff
                    handoff(store.root,identity(os.getpid()))
                    return
                dispatch_one(store)
            except Exception as exc:
                print(time.strftime("%FT%T"), type(exc).__name__, str(exc), flush=True)
            time.sleep(1)


def ensure_daemon(store):
    path = store.root / "runtime/daemon.json"
    if path.exists() and owns(json.loads(path.read_text())):
        stamp=store.root/'runtime/daemon-code.json'
        if not stamp.exists() or json.loads(stamp.read_text()).get('generation')!=daemon_generation():
            raise Conflict('running daemon uses stale code; use restart-daemon at an idle boundary')
        return json.loads(path.read_text())
    with (store.root / "runtime/daemon.log").open("ab") as log:
        p = subprocess.Popen([sys.executable, "-m", "rlflow.cli", "--state-dir", str(store.root), "_daemon"],
                             cwd=CODE, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    return identity(p.pid)


def daemon_generation():
    return sha({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((CODE/'rlflow').glob('*.py'))})


def restart_daemon(store):
    state=store.replay()
    # The independent worker/job supervisors own active work. Restart only the dispatcher.
    # Preserve pause and autonomous selections; reconciliation precedes all new dispatch.
    path=store.root/'runtime/daemon.json'
    record=json.loads(path.read_text()) if path.exists() else None
    if owns(record):
        argv=Path(f'/proc/{record["pid"]}/cmdline').read_bytes().split(b'\0')
        if b'rlflow.cli' not in argv or b'_daemon' not in argv:
            raise Conflict('registered process is not an rlflow daemon')
        if owns(record):os.kill(record['pid'],signal.SIGTERM)
        for _ in range(50):
            if not owns(record):break
            time.sleep(.1)
        if owns(record):raise Conflict('old daemon has not stopped')
    return ensure_daemon(store)
