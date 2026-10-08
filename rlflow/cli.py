import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from .store import Store, canonical, sha, Conflict
from .policy import COORDINATION, STOP_PATHS, make_proposal, show_proposal, decide, stopped, available, require_stage


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def parser():
    p = argparse.ArgumentParser(description="rlflow 独立控制面（项目 Runner 未配置）")
    p.add_argument("--state-dir", type=Path, default=COORDINATION / "research")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("doctor", "status", "pause", "resume", "dispatch", "self-test", "init-demo", "rebuild", "storage-audit", "storage-snapshot", "storage-export", "storage-recover", "rollback", "_daemon", 'restart-daemon'):
        command = sub.add_parser(name)
        if name == 'status':
            command.add_argument('--watch', action='store_true')
        if name in {'pause', 'resume'}:
            command.add_argument('--package')
    start = sub.add_parser("start")
    task_input = start.add_mutually_exclusive_group(required=True)
    task_input.add_argument("--task")
    task_input.add_argument("--task-file", type=Path)
    task_input.add_argument("--package-file", type=Path)
    task_input.add_argument("--goal-file", type=Path)
    start.add_argument("--stage")
    start.add_argument("--repo", type=Path)
    start.add_argument("--key")
    start.add_argument("--role-calls", type=int, default=6)
    start.add_argument("--wall-seconds", type=int, default=3600)
    start.add_argument("--fake-starts", type=int, default=0)
    start.add_argument('--manual', action='store_true', help='legacy proposal: do not create/start the task on approval')
    start.add_argument("--module-root", action="append", default=[])
    start.add_argument("--protected-path", action="append", default=[])
    start.add_argument("--cpu-runtime-root", type=Path)
    start.add_argument("--cpu-python", type=Path)
    start.add_argument("--cpu-address-space-gib", type=int, default=8)
    extension = sub.add_parser("propose-extension")
    extension.add_argument("--stage", required=True)
    extension.add_argument("--task", required=True)
    extension.add_argument("--role-calls", type=int, default=1)
    extension.add_argument("--wall-seconds", type=int, default=600)
    extension.add_argument("--reason", required=True)
    extension.add_argument('--manual', action='store_true', help='legacy single Evaluator extension')
    extension.add_argument('--next-role', choices=['PI','Engineer','Evaluator','Critic','Designer','Scout'])
    sub.add_parser('model-policy')
    mb = sub.add_parser('model-budget')
    mb.add_argument('--stage', required=True)
    mb.add_argument('--sol-calls', type=int, required=True)
    mb.add_argument('--astra-calls', type=int, required=True)
    mb.add_argument('--reason', required=True)
    consult = sub.add_parser('consult')
    consult.add_argument('--stage', required=True)
    consult.add_argument('--role', choices=['Critic','Designer','Scout'], required=True)
    consult.add_argument('--task', required=True)
    consult.add_argument('--key')
    ec = sub.add_parser('escalation-case')
    ec.add_argument('--file', type=Path, required=True)
    eq = sub.add_parser('escalate')
    eq.add_argument('--case', required=True)
    log = sub.add_parser("logs")
    log.add_argument("--session")
    log.add_argument("--lines", type=int, default=40)
    proposal = sub.add_parser("proposal")
    proposal.add_argument("action", choices=["show"])
    proposal.add_argument("id")
    for name in ("approve", "reject"):
        a = sub.add_parser(name)
        a.add_argument("id")
        a.add_argument("--sha256", required=True)
        a.add_argument("--reason", default="explicit local user decision")
    submit = sub.add_parser("submit-experiment")
    submit.add_argument("--stage")
    submit.add_argument("--spec", type=Path)
    submit.add_argument("--key")
    submit.add_argument("--backend", default="fake")
    submit.add_argument("--duration", type=float, default=.05)
    submit.add_argument("--mode", default="normal")
    status = sub.add_parser("job-status")
    status.add_argument("id")
    record = sub.add_parser("record-decision")
    record.add_argument("--session", required=True, help="only a dispatched role's immutable result can be registered")
    reconsider = sub.add_parser("reconsider-result")
    reconsider.add_argument("--session", required=True, help="revalidate one saved rejected Evaluator result without a new role call")
    activate = sub.add_parser("activate")
    activate.add_argument("--report", type=Path, required=True)
    release=sub.add_parser('deploy-control')
    release.add_argument('--report', type=Path, required=True)
    sub.add_parser('reconcile')
    for name in ('usage','usage-reconcile'):
        sub.add_parser(name).add_argument('session')
    adoption = sub.add_parser('propose-adoption')
    adoption.add_argument('--spec',type=Path,required=True)
    exp = sub.add_parser('propose-experiment')
    exp.add_argument('--spec', type=Path, required=True)
    for name in ('collect-experiment','cancel-experiment','reconcile-experiment'):
        sub.add_parser(name).add_argument('id')
    package = sub.add_parser('package-status')
    package.add_argument('id')
    revoke = sub.add_parser('revoke')
    revoke.add_argument('id')
    revoke.add_argument('--reason', required=True)
    correction = sub.add_parser('correct-prelaunch')
    correction.add_argument('--session', required=True)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        if a.command in {"init-demo", "activate"}:
            raise Conflict("Legacy project migration/demo authorization is unavailable; use start --goal-file")
        from . import engine, jobs, migration
        if a.command == "self-test":
            code = Path(__file__).resolve().parents[1]
            with tempfile.TemporaryDirectory(prefix="rlflow-self-test-") as temporary:
                env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "RLFLOW_TEST_STATE": temporary}
                r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests", "--basetemp", temporary + "/pytest"], cwd=code, env=env, capture_output=True, text=True)
                print(r.stdout + r.stderr, end="")
                from .verification import code_identity
                from .store import atomic
                atomic(a.state_dir / "runtime/self-test.json", canonical({"exit_code": r.returncode, "code_identity": code_identity(),
                       "time": time.time(), "stdout": r.stdout, "stderr": r.stderr, "isolated_state": True}))
                return r.returncode
        store = Store(a.state_dir,allow_rebuild=a.command in {"rebuild","storage-recover"})
        if a.command == "storage-audit":
            audited = store.audit()
            matches=audited==store.replay()
            output({"version":audited["version"],"projection_matches":matches})
            if not matches:return 1
        elif a.command == "storage-recover":
            output({"version":store.recover()["version"]})
        elif a.command == "storage-snapshot":
            output(store.snapshot())
        elif a.command == "storage-export":
            output(store.export())
        elif a.command == "_daemon":
            engine.daemon(store.root)
        elif a.command == 'restart-daemon':
            output({'daemon':engine.restart_daemon(store),'paused':store.view()['paused']})
        elif a.command == 'usage':
            output(store.get('usage',a.session,{'complete':False,'actual_cost_status':'UNKNOWN'}))
        elif a.command == 'usage-reconcile':
            from .usage import reconcile
            output(reconcile(store,a.session))
        elif a.command == "doctor":
            from .isolation import doctor
            report = doctor(store.root)
            output(report)
            return 0 if report.get("ok", False) else 1
        elif a.command == 'model-policy':
            from .model_policy import load_policy
            from .role_config import load_role
            from .contracts import ROLES
            output({'policy':load_policy(), 'roles':{r:load_role(r) for r in ROLES}})
        elif a.command == 'model-budget':
            from .model_policy import set_budget
            state = set_budget(store,a.stage,a.sol_calls,a.astra_calls,a.reason)
            output(state['stages'][a.stage]['compute'])
        elif a.command == 'consult':
            tid = engine.add_task(store,a.stage,a.task,a.key,consultation_role=a.role)
            output({'task':tid,'daemon':engine.ensure_daemon(store)})
        elif a.command == 'escalation-case':
            from .escalations import register_case
            output(register_case(store,json.loads(a.file.read_text())))
        elif a.command == 'escalate':
            from .escalations import queue
            output(queue(store,a.case))
        elif a.command == "init-demo":
            migration.import_history(store)
            migration.seed_demo(store)
            output({"stage": "CPU-DEMO", "repo": str(store.root / "workspaces/budget-parser-demo")})
        elif a.command == "start":
            if a.goal_file:
                from .packages import propose,from_goal
                output(show_proposal(store,propose(store,from_goal(json.loads(a.goal_file.read_text())))))
                return 0
            if a.package_file:
                from .packages import propose
                output(show_proposal(store, propose(store, json.loads(a.package_file.read_text()))))
                return 0
            if not a.stage:
                raise Conflict('--stage is required for a legacy single task')
            task_text = a.task_file.read_text() if a.task_file is not None else a.task
            state = store.view()
            if a.stage not in state["stages"]:
                pid = make_proposal(
                    store, a.stage, a.repo, task_text,
                    {"role_calls": a.role_calls, "wall_seconds": a.wall_seconds, "fake_starts": a.fake_starts},
                    module_roots=a.module_root or None,
                    protected_paths=a.protected_path or None,
                    cpu_runtime_root=a.cpu_runtime_root,
                    cpu_python=a.cpu_python,
                    cpu_address_space_gib=a.cpu_address_space_gib,
                    stage_loop=not a.manual,
                )
                output(show_proposal(store, pid))
                return 0
            task_id = engine.add_task(store, a.stage, task_text, a.key)
            output({"task": task_id, "daemon": engine.ensure_daemon(store)})
        elif a.command == "propose-extension":
            from .policy import make_extension_proposal
            pid = make_extension_proposal(store, a.stage, a.task, a.role_calls, a.wall_seconds, a.reason,
                                          stage_loop=not a.manual, next_role=a.next_role)
            output(show_proposal(store, pid))
        elif a.command == 'deploy-control':
            from .releases import deploy
            output(deploy(store,a.report))
        elif a.command == 'reconcile':
            output(engine.reconcile(store))
        elif a.command == 'correct-prelaunch':
            from .accounting import correct_prelaunch
            output(correct_prelaunch(store, a.session)['accounting_corrections'][a.session])
        elif a.command == 'package-status':
            output(store.view().get('packages', {})[a.id])
        elif a.command == 'revoke':
            from .authorizations import revoke
            output(revoke(store, a.id, a.reason))
        elif a.command == "status":
            if a.watch:
                try:
                    while True:
                        main(['--state-dir', str(store.root), 'status'])
                        time.sleep(2)
                except KeyboardInterrupt:
                    return 0
            state=store.view();connection=state['tasks'].db
            tasks=store.summaries('tasks',('status','stage_id','next_role','repair_rounds','completion','last_error'),connection)
            stages=store.summaries('stages',('budget','used_calls','reserved_calls','used_seconds','reserved_seconds','used_fake_starts','infrastructure_seconds','compute','budget_reserves','pool_usage'),connection)
            sessions=store.summaries('sessions',('role','status','directory','launch_phase','generation','resources','resource_guarantees','model_accounting','receipt.resource_usage'),connection)
            output({'version':state['version'],'projection_version':state['version'],'enabled':state['enabled'],'paused':state['paused'],
                'packages':store.summaries('packages',('id','status','paused','tasks','achievements','next_actions'),connection),
                'goals':store.summaries('goals',('id','description','package_id','status'),connection),
                'autonomous_tasks':state.get('autonomous_tasks',[]),
                'stage_loops':{tid:{'status':tasks[tid]['status'],'next_role':tasks[tid]['next_role'],'remaining':available(stages[tasks[tid]['stage_id']])} for tid in state.get('autonomous_tasks',[]) if tid in tasks},
                'dispatch_policy':'paused controls manual tasks; autonomous_tasks are approved to run; pause clears both',
                'STOP':stopped(store.root),'tasks':tasks,
                'budgets':{k:{'remaining':available(v),**{field:v.get(field,0) for field in ('used_calls','reserved_calls','used_seconds','reserved_seconds','infrastructure_seconds')}} for k,v in stages.items()},
                'budget_reserves':{k:{'limits':v['budget_reserves'],'usage':v.get('pool_usage',{})} for k,v in stages.items() if 'budget_reserves' in v},
                'compute_budgets':{k:v.get('compute') for k,v in stages.items()},'sessions':sessions,
                'blocked_reasons':{k:v['last_error'] for k,v in tasks.items() if v.get('last_error')},
                'usage':store.summaries('usage',('input_tokens','output_tokens','cached_tokens','model','complete','estimated_cost','actual_cost_status'),connection),
                'proposals':store.summaries('proposals',('id','version','sha256','shown','content.scope','content.stage_id'),connection),
                'jobs':store.summaries('jobs',('id','stage','status','reserved_resources','used_resources','launch_phase','resource_guarantees'),connection),
                'historical_summary':state['historical'].get('summary',{})})
        elif a.command == "logs":
            path = store.root / "runtime/daemon.log"
            if a.session:
                se = store.view()["sessions"][a.session]
                path = Path(se["directory"]) / "events.jsonl"
            print("\n".join(path.read_text().splitlines()[-a.lines:]) if path.exists() else "No logs yet")
        elif a.command in {"pause", "resume"}:
            if a.package:
                from .packages import pause
                if a.command == 'resume': engine.reconcile(store)
                output(pause(store, a.package, a.command == 'pause')['packages'][a.package])
                if a.command == 'resume': engine.ensure_daemon(store)
                return 0
            if a.command == "resume":
                state = engine.reconcile(store)
                if stopped(store.root) or any(s["status"] == "RECONCILE" for s in state["sessions"].values()):
                    raise Conflict("STOP or uncertain launch must be reconciled before resume")
            def change_pause(s):
                s["paused"] = a.command == "pause"
                if a.command == 'pause':
                    s['autonomous_tasks'] = []
                    for package in s.get('packages', {}).values(): package['paused'] = True
                if a.command == "resume":
                    from .isolation import require_doctor
                    require_doctor(store.root)
                    for task in s["tasks"].values():
                        if task["status"] == "ROLE_ERROR":
                            task["status"] = "QUEUED"
                        if task["status"] == "QUEUED" and task.get("last_failure", {}).get("kind") == "ROLE_OUTPUT":
                            task["last_failure"]["blocked"] = False
            state = store.transact("PAUSED" if a.command == "pause" else "RESUMED", a.command + ":" + str(time.time_ns()), change_pause)
            if a.command == "resume":
                engine.ensure_daemon(store)
            output({"paused": state["paused"]})
        elif a.command == "dispatch":
            engine.reconcile(store)
            output({"session": engine.dispatch_one(store, allow_paused=True)})
        elif a.command == "record-decision":
            engine.accept_result(store, a.session)
            output(store.view()["sessions"][a.session])
        elif a.command == "reconsider-result":
            state = engine.reconsider_result(store, a.session)
            output({"session": state["sessions"][a.session],
                    "task": state["tasks"][state["sessions"][a.session]["task_id"]],
                    "accounting": "unchanged"})
        elif a.command == "proposal":
            output(show_proposal(store, a.id))
        elif a.command in {"approve", "reject"}:
            state = decide(store, a.id, a.sha256, "APPROVED" if a.command == "approve" else "REJECTED", a.reason)
            response = {"proposal": a.id, "decision": a.command}
            if a.command == 'approve' and state['proposals'][a.id]['content'].get('execution', {}).get('mode') in {'stage_loop', 'package'}:
                response['autonomous_tasks'] = state.get('autonomous_tasks', [])
                response['daemon'] = engine.ensure_daemon(store)
            output(response)
        elif a.command == 'propose-adoption':
            from .adoption import propose
            output(show_proposal(store,propose(store,json.loads(a.spec.read_text()))))
        elif a.command == 'propose-experiment':
            from .experiments import propose
            output(show_proposal(store, propose(store,json.loads(a.spec.read_text()))))
        elif a.command in {'collect-experiment','cancel-experiment','reconcile-experiment'}:
            from . import experiments
            action={'collect-experiment':experiments.collect,'cancel-experiment':experiments.cancel,'reconcile-experiment':experiments.reconcile}[a.command]
            output(action(store,a.id))
        elif a.command == "submit-experiment":
            if a.spec:
                from .experiments import submit
                output(submit(store,json.loads(a.spec.read_text())))
                return 0
            if not a.stage or not a.key: raise Conflict('legacy fake submission requires stage and key')
            spec = {"backend": a.backend, "duration": a.duration, "mode": a.mode}
            jobs._validate(spec)
            if stopped(store.root):
                raise Conflict("STOP")
            jid = "J-" + sha({"stage": a.stage, "key": a.key})[:16]
            newly_reserved = []
            def reserve(s):
                st = require_stage(s, a.stage)
                if s["paused"] or stopped(store.root) or available(st)["fake_starts"] < 1:
                    raise Conflict("paused, STOP, or fake budget exhausted")
                st["used_fake_starts"] += 1
                s["jobs"][jid] = {"stage": a.stage, "spec": spec, "status": "START_INTENT"}
                newly_reserved.append(True)
            state = store.transact("JOB_RESERVED", jid + ":reserve", reserve, object_id=jid)
            if state["jobs"][jid]["spec"] != spec:
                raise Conflict("idempotency key content mismatch")
            if not newly_reserved:
                if (store.root / "jobs" / jid / "state.json").exists():
                    output(jobs.reconcile(store.root, jid))
                else:
                    store.transact("JOB_RECONCILE_REQUIRED", jid + ":uncertain", lambda s: s["jobs"][jid].update(status="RECONCILE"), object_id=jid)
                    output({"job_id": jid, "state": "RECONCILE", "reason": "existing start intent has no confirmed launch artifact; no restart/refund"})
            else:
                output(jobs.submit(store.root, jid, spec, [str(p) for p in [*STOP_PATHS, store.root / "STOP"]]))
        elif a.command == "job-status":
            result = jobs.reconcile(store.root, a.id)
            store.transact("JOB_OBSERVED", a.id + ":observe:" + sha(result), lambda s: s["jobs"][a.id].update(status=result["state"]), object_id=a.id)
            output(result)
        elif a.command == "rebuild":
            output({"version": store.rebuild()["version"]})
        elif a.command == "activate":
            migration.activate(store, a.report)
            output({"enabled": True, "capabilities": "CPU only"})
        elif a.command == "rollback":
            migration.rollback(store)
            output({"enabled": False, "budgets_and_events": "retained"})
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"rlflow: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
