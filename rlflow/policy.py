"""Trusted user entry and conservative, content-bound CPU stage authorization."""
from pathlib import Path
import hashlib
import subprocess
import time
import os
import stat
import shutil
import tempfile
from pathlib import PurePosixPath
from .store import atomic, canonical, sha, Conflict

# Authority paths belong to the authorized workspace, never the relocatable code release.
WORKSPACE = Path.home() / ".local/share/rlflow-standalone"
COORDINATION = WORKSPACE / "coordination"
STOP_PATHS = [COORDINATION / "commander/STOP", COORDINATION / "executor/STOP", COORDINATION / "STOP", WORKSPACE / "STOP"]


def stopped(root):
    return [str(p) for p in [*STOP_PATHS, Path(root) / "STOP"] if p.exists()]


def git(repo, *args):
    return git_bytes(repo,*args).decode().strip()


def git_bytes(repo,*args):
    # Candidate-local helpers must never execute in the trusted control plane.
    if args and args[0]=='diff':args=('diff','--no-ext-diff','--no-textconv',*args[1:])
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL')}
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(['/usr/bin/git','--no-pager','-c','core.fsmonitor=false',
                                    '-c','core.hooksPath=/dev/null','-C',str(repo),*args],env=env,stderr=subprocess.STDOUT)


def git_diff_bytes(repo, base, input_contract=None):
    """Return one binary diff including untracked files without changing .git."""
    repo = Path(repo).resolve(strict=True)
    paths=['.']
    if input_contract is not None:
        from .files import source_names
        paths=sorted(set(source_names(repo,input_contract))|set(input_contract['manifest']['source_files']))
        if not paths:return b''
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
    with tempfile.TemporaryDirectory(prefix='rlflow-diff-') as temporary:
        index = Path(temporary) / 'index'
        shutil.copyfile(repo / '.git/index', index)
        env['GIT_INDEX_FILE'] = str(index)
        command = ['/usr/bin/git', '--no-pager', '-c', 'core.fsmonitor=false',
                   '-c', 'core.hooksPath=/dev/null', '-C', str(repo)]
        untracked = subprocess.check_output(
            [*command, 'ls-files', '--others', *(['--exclude-standard'] if input_contract is None else []), '-z','--',*paths],
            env=env, stderr=subprocess.STDOUT,
        ).split(b'\0')
        names = [name.decode('utf-8') for name in untracked if name]
        if names:
            subprocess.check_output([*command, 'add', '-N', '-f', '--', *names], env=env,
                                    stderr=subprocess.STDOUT)
        return subprocess.check_output(
            [*command, 'diff', '--binary', '--no-ext-diff', '--no-textconv', base, '--', *paths],
            env=env, stderr=subprocess.STDOUT,
        )


def candidate(repo, input_contract=None):
    if Path(repo).is_symlink():raise Conflict('candidate root must not be a symlink')
    repo = Path(repo).resolve(strict=True)
    metadata=repo/'.git'
    if metadata.is_symlink() or not metadata.is_dir():
        raise Conflict('candidate must be a standalone Git checkout, not a shared worktree')
    if input_contract is not None:
        from .files import SourceIndex,source_names
        # Git metadata remains within the old safety boundary.
        for p in metadata.rglob('*'):
            info=p.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or stat.S_ISREG(info.st_mode) and info.st_nlink!=1:
                raise Conflict('unsafe Git metadata')
        for name in ('objects/info/alternates','objects/info/http-alternates','commondir'):
            if (metadata/name).exists():raise Conflict('shared Git metadata')
        names=source_names(repo,input_contract)
        files=SourceIndex().scan(repo,names,boundary=True)['files']
        if source_names(repo,input_contract)!=names:raise Conflict('source membership changed during scan')
        if Path(git(repo,'rev-parse','--show-toplevel')).resolve()!=repo or Path(git(repo,'rev-parse','--absolute-git-dir')).resolve()!=metadata:
            raise Conflict('Git root differs from candidate')
        return {"path":str(repo),"head":git(repo,"rev-parse","HEAD"),"tree_sha256":sha(files),"files":files}
    files = {}
    verified_stats={}
    paths=sorted(repo.rglob("*"))
    for p in paths:
        rel = p.relative_to(repo)
        info=p.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise Conflict(f'candidate contains a symlink or special file: {rel}')
        if stat.S_ISREG(info.st_mode) and info.st_nlink!=1:
            raise Conflict(f'candidate contains a shared hardlink: {rel}')
        if str(rel) in {'.git/objects/info/alternates','.git/objects/info/http-alternates','.git/commondir'}:
            raise Conflict('candidate Git metadata references shared storage')
        if any(x in {".git", "__pycache__", ".pytest_cache", ".venv"} for x in rel.parts):
            continue
        if p.is_symlink():
            raise Conflict(f"candidate symlink requires clarification: {rel}")
        if p.is_file():
            from .files import stream_digest
            files[str(rel)] = stream_digest(p, root=repo)
            from .files import stamp
            verified_stats[p]=stamp(info)
    if sorted(repo.rglob('*'))!=paths or any(stamp(p.lstat())!=value for p,value in verified_stats.items()):
        raise Conflict('legacy candidate changed during scan')
    if Path(git(repo,'rev-parse','--show-toplevel')).resolve()!=repo or Path(git(repo,'rev-parse','--absolute-git-dir')).resolve()!=metadata:
        raise Conflict('Git root differs from candidate')
    return {"path": str(repo), "head": git(repo, "rev-parse", "HEAD"), "tree_sha256": sha(files), "files": files}


def available(stage):
    b = stage["budget"]
    return {"role_calls": b["role_calls"] - stage["used_calls"] - stage.get("reserved_calls", 0),
            "wall_seconds": b["wall_seconds"] - stage["used_seconds"] - stage["reserved_seconds"],
            "fake_starts": b["fake_starts"] - stage.get("used_fake_starts", 0)}


def require_stage(state, sid):
    stage = state["stages"].get(sid)
    if not stage or stage["status"] != "AUTHORIZED":
        raise Conflict("stage has no effective authorization")
    if stage.get("repair_id"):
        from .repairs import validate_stage
        validate_stage(state, stage)
    elif stage.get("package_id"):
        from .packages import require_package
        require_package(state, stage)
    elif stage.get("approval_id"):
        a = state["approvals"].get(stage["approval_id"], {})
        p = state["proposals"].get(a.get("proposal_id"), {})
        content = p.get("content", {})
        if a.get("decision") != "APPROVED" or a.get("revoked", False) or p.get("revoked", False):
            raise Conflict("approval revoked or rejected")
        digest = sha(content)
        if a.get("proposal_sha256") != digest or p.get("sha256") != digest:
            raise Conflict("proposal content changed")
        if a.get("proposal_version") != p.get("version"):
            raise Conflict("approval proposal version mismatch")
        if a.get("scope") != "STAGE" or a.get("stage_id") != sid or content.get("scope") != "STAGE" or content.get("stage_id") != sid:
            raise Conflict("approval scope mismatch")
        expected_budget = dict(content.get("budget", {}))
        for extension_id in stage.get("approval_extensions", []):
            extension = state["approvals"].get(extension_id, {})
            extension_proposal = state["proposals"].get(extension.get("proposal_id"), {})
            extension_content = extension_proposal.get("content", {})
            if (extension.get("decision") != "APPROVED" or extension.get("revoked", False)
                    or extension_proposal.get("revoked", False)
                    or extension_content.get("scope") != "STAGE_EXTENSION"
                    or extension_content.get("stage_id") != sid
                    or sha(extension_content) != extension.get("proposal_sha256")
                    or sha(extension_content) != extension_proposal.get("sha256")):
                raise Conflict("stage extension approval invalid")
            additional = extension_content["additional_budget"]
            for key in ("role_calls", "wall_seconds", "fake_starts"):
                expected_budget[key] += additional[key]
        if stage.get("budget") != expected_budget:
            raise Conflict("stage budget differs from approved limits")
        for field in ("repo", "module_roots", "categories", "protected_paths", "cpu_runtime"):
            if stage.get(field) != content.get(field):
                raise Conflict("stage scope differs from approved " + field)
        if stage.get("scope") != content.get("task") or stage.get("authorization") != digest:
            raise Conflict("stage authorization differs from approved content")
    budget = stage.get("budget", {})
    for key in ("role_calls", "wall_seconds", "fake_starts"):
        if type(budget.get(key)) is not int or budget[key] < 0:
            raise Conflict("unknown or invalid stage budget; reconciliation required")
    for key in ("used_calls", "used_seconds", "reserved_seconds", "used_fake_starts"):
        value = stage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < float("inf"):
            raise Conflict("unknown or invalid consumption; reconciliation required")
    if stage.get("cpu_only") is not True:
        raise Conflict("only CPU stages are supported")
    _validated_candidate_paths(stage["repo"], stage["module_roots"], stage["protected_paths"])
    _validate_cpu_runtime(stage.get("cpu_runtime"))
    return stage


def _validated_candidate_paths(repo, module_roots, protected_paths):
    repo = Path(repo).resolve(strict=True)
    if not module_roots:
        raise Conflict("CPU stage needs at least one module root")
    normalized = {}
    for label, values in (("module root", module_roots), ("protected path", protected_paths)):
        rows = []
        for value in values:
            if not isinstance(value, str) or not value or "\\" in value:
                raise Conflict(f"invalid {label}")
            pure = PurePosixPath(value)
            if pure.is_absolute() or ".." in pure.parts:
                raise Conflict(f"invalid {label}")
            try:
                path = (repo / pure).resolve(strict=True)
            except FileNotFoundError as exc:
                raise Conflict(f"{label} does not exist") from exc
            if path != repo and not path.is_relative_to(repo):
                raise Conflict(f"{label} escapes candidate")
            rows.append(pure.as_posix())
        normalized[label] = rows
    return normalized["module root"], normalized["protected path"]


def _validate_cpu_runtime(runtime):
    if runtime is None:
        return None
    if set(runtime) != {"root", "python", "python_sha256", "address_space_bytes"}:
        raise Conflict("invalid CPU runtime binding")
    root = Path(runtime["root"]).resolve(strict=True)
    python = Path(runtime["python"]).resolve(strict=True)
    if (not root.is_dir() or not python.is_file() or not python.is_relative_to(root)
            or not os.access(python, os.X_OK)):
        raise Conflict("CPU Python must be a regular file within its read-only runtime root")
    if hashlib.sha256(python.read_bytes()).hexdigest() != runtime["python_sha256"]:
        raise Conflict("CPU Python identity changed")
    memory = runtime["address_space_bytes"]
    if type(memory) is not int or not 2 * 1024**3 <= memory <= 16 * 1024**3:
        raise Conflict("CPU address-space limit must be an integer from 2 to 16 GiB")
    return runtime


def _cpu_runtime(root, python, address_space_gib):
    if root is None and python is None:
        return None
    if root is None or python is None:
        raise Conflict("--cpu-runtime-root and --cpu-python must be supplied together")
    root = Path(root).resolve(strict=True)
    python = Path(python).resolve(strict=True)
    return _validate_cpu_runtime({"root": str(root), "python": str(python),
                                  "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
                                  "address_space_bytes": address_space_gib * 1024**3})


def new_stage(sid, repo, task, budget, authorization, *, approval_id=None,
              module_roots=None, protected_paths=None, cpu_runtime=None, input_contract=None):
    from .model_policy import new_budget
    if type(budget.get("role_calls")) is not int or type(budget.get("wall_seconds")) is not int:
        raise Conflict("budget must contain integer role_calls and wall_seconds")
    if not 1 <= budget["role_calls"] <= 100 or not 1 <= budget["wall_seconds"] <= 86400:
        raise Conflict("invalid CPU stage budget")
    if type(budget.get("fake_starts")) is not int or not 0 <= budget["fake_starts"] <= 100:
        raise Conflict("invalid fake job budget")
    module_roots, protected_paths = _validated_candidate_paths(
        repo, module_roots or ["."], protected_paths or [".git"])
    _validate_cpu_runtime(cpu_runtime)
    return {"id": sid, "status": "AUTHORIZED", "repo": str(Path(repo).resolve()), "scope": task,
            "module_roots": module_roots, "protected_paths": protected_paths,
            "cpu_runtime": cpu_runtime, "categories": ["ENGINEERING_FIX"], "budget": budget,
            "used_calls": 0, "used_seconds": 0, "reserved_seconds": 0, "used_fake_starts": 0,
            "authorization": authorization, "approval_id": approval_id, "cpu_only": True,
            "baseline": candidate(repo,input_contract), "per_call_seconds": min(900, budget["wall_seconds"]),
            "compute": new_budget(budget["role_calls"])}


def make_proposal(store, sid, repo, task, budget, *, module_roots=None,
                  protected_paths=None, cpu_runtime_root=None, cpu_python=None,
                  cpu_address_space_gib=8, stage_loop=False):
    if repo is None:
        raise Conflict("new stage needs --repo pointing to an isolated CPU Git repository")
    repo = Path(repo).resolve(strict=True)
    # A stage never grants direct access to existing product/runtime/control roots.
    if not repo.is_relative_to(store.root / "workspaces"):
        raise Conflict(f"CPU stage repository must be under {store.root / 'workspaces'}; clone there first")
    module_roots, protected_paths = _validated_candidate_paths(
        repo, module_roots or ["."], protected_paths or [".git"])
    runtime = _cpu_runtime(cpu_runtime_root, cpu_python, cpu_address_space_gib)
    content = {"schema_version": "rlflow-proposal/1", "stage_id": sid, "scope": "STAGE",
               "repo": str(repo), "baseline": candidate(repo), "task": task,
               "module_roots": module_roots, "protected_paths": protected_paths,
               "cpu_runtime": runtime, "categories": ["ENGINEERING_FIX"], "budget": budget,
               "evidence": [], "counterevidence": [], "replacement": "none",
               "verification": "Engineer CPU self-test then independent Evaluator; contract changes need clarification",
               "stop_conditions": ["STOP", "budget exhaustion", "unresolved contract"],
               "preconditions": ["doctor PASS", "no real backend", "no GPU/runtime", "exact candidate"],
               "authorization_version": "workflow-0.2-cpu"}
    if stage_loop:
        content['execution'] = {'mode': 'stage_loop', 'start_on_approval': True,
                                'description': 'PI, implementation, independent review and bounded rework share the approved total budget; stop on completion or a blocking gate.'}
    digest = sha(content)
    pid = "P-" + digest[:16]
    def mutate(s):
        if sid in s["stages"]:
            raise Conflict("stage already exists; budget does not reset")
        s["proposals"][pid] = {"id": pid, "version": 1, "sha256": digest, "content": content, "shown": False}
        return {"proposal_id": pid}
    store.transact("PROPOSAL_CREATED", "proposal:" + digest, mutate, object_id=pid)
    atomic(store.root / "proposals" / (pid + ".json"), canonical(content))
    return pid


def make_extension_proposal(store, sid, task_id, role_calls, wall_seconds, reason, *, stage_loop=False, next_role=None):
    state = store.view()
    stage = require_stage(state, sid)
    if any(x["stage_id"] == sid and x["status"] in {"START_INTENT", "RUNNING", "RECONCILE"}
           for x in state["sessions"].values()):
        raise Conflict("cannot extend a stage with an active role")
    task = state["tasks"].get(task_id)
    if not task or task["stage_id"] != sid or task["status"] not in {
        "INFRASTRUCTURE_ERROR", "CONTRACT_DECISION", "ROLE_ERROR", "QUEUED", "BUDGET_EXHAUSTED"
    }:
        raise Conflict("task is not at an extension boundary")
    minimum_wall_seconds = 0 if stage_loop else 1
    if (type(role_calls) is not int or type(wall_seconds) is not int
            or not 1 <= role_calls <= (100 if stage_loop else 1)
            or not minimum_wall_seconds <= wall_seconds <= (86400 if stage_loop else 900)
            or stage['budget']['role_calls'] + role_calls > 100
            or stage['budget']['wall_seconds'] + wall_seconds > 86400):
        raise Conflict("invalid extension: cumulative maximum 100 calls / 86400 seconds; manual review allows one call / 900 seconds")
    selected_role = (next_role or task['next_role']) if stage_loop else 'Evaluator'
    if selected_role not in {'PI', 'Engineer', 'Evaluator', 'Critic', 'Designer', 'Scout'}:
        raise Conflict('invalid continuation role')
    if stage_loop and (task['status'] not in {'QUEUED', 'BUDGET_EXHAUSTED'}
                       or task.get('pending_escalation') or task.get('last_failure', {}).get('blocked')):
        raise Conflict('resolve the contract, infrastructure failure or model escalation before authorizing a stage loop')
    if not reason.strip():
        raise Conflict("extension reason required")
    current = candidate(task["repo"],task.get("input_contract"))
    content = {
        "schema_version": "rlflow-proposal/1", "scope": "STAGE_EXTENSION",
        "stage_id": sid, "task_id": task_id, "task_version": task["version"],
        "next_role": selected_role, "repo": task["repo"], "candidate": current,
        "candidate_diff_sha256": hashlib.sha256(git_diff_bytes(task["repo"], task["baseline"]["head"],task.get("input_contract"))).hexdigest(),
        "recorded_budget": dict(stage["budget"]),
        "recorded_usage": {k: stage[k] for k in ("used_calls", "used_seconds", "reserved_seconds", "used_fake_starts")},
        "additional_budget": {"role_calls": role_calls, "wall_seconds": wall_seconds, "fake_starts": 0},
        "additional_compute": {"sol": role_calls, "astra": 0},
        "reason": reason, "replacement": "none; cumulative usage is preserved",
        "verification": "one independent Evaluator CPU review only",
        "stop_conditions": ["STOP", "extension exhaustion", "candidate drift"],
    }
    if stage_loop:
        content['execution'] = {'mode': 'stage_loop', 'start_on_approval': True}
        content['verification'] = 'Continue the bound task through independent review and ordinary rework within the cumulative stage budget; no per-review approval.'
    digest = sha(content)
    pid = "P-" + digest[:16]
    def mutate(s):
        s["proposals"][pid] = {"id": pid, "version": 1, "sha256": digest,
                               "content": content, "shown": False}
    store.transact("PROPOSAL_CREATED", "proposal:" + digest, mutate, object_id=pid)
    atomic(store.root / "proposals" / (pid + ".json"), canonical(content))
    return pid


def show_proposal(store, pid):
    p = store.view()["proposals"][pid]
    if sha(p["content"]) != p["sha256"]:
        raise Conflict("proposal hash mismatch")
    store.transact("PROPOSAL_SHOWN", "shown:" + p["sha256"], lambda s: s["proposals"][pid].update(shown=True), object_id=pid, producer="user-cli")
    return {"proposal_id": pid, "sha256": p["sha256"], "content": p["content"]}


def decide(store, pid, digest, decision, reason):
    if decision not in {"APPROVED", "REJECTED"}:
        raise Conflict("invalid approval decision")
    def mutate(s):
        p = s["proposals"][pid]
        if not p["shown"] or sha(p["content"]) != digest or p["sha256"] != digest:
            raise Conflict("must show and approve exact proposal sha256")
        c = p["content"]
        aid = "A-" + digest[:16]
        if aid in s["approvals"]:
            raise Conflict("decision already recorded; use explicit revocation for an approval")
        if decision == "APPROVED" and c["scope"] in {"SANDBOX_ONLY","MAINLINE_ADOPTION"}:
            from .adoption import approve_in
            approve_in(s,c,aid)
        elif decision == "APPROVED" and c["scope"] == "PACKAGE":
            from .packages import approve_in
            approve_in(s, c, aid, digest)
        elif decision == "APPROVED" and c["scope"] == "STAGE":
            if candidate(c["repo"]) != c["baseline"]:
                raise Conflict("candidate changed since proposal; create a new proposal")
            if c["stage_id"] in s["stages"]:
                raise Conflict("stage exists; cannot reset cumulative budget")
            s["stages"][c["stage_id"]] = new_stage(
                c["stage_id"], c["repo"], c["task"], c["budget"], digest,
                approval_id=aid, module_roots=c["module_roots"],
                protected_paths=c["protected_paths"], cpu_runtime=c.get("cpu_runtime"))
        elif decision == "APPROVED" and c["scope"] == "STAGE_EXTENSION":
            stage = require_stage(s, c["stage_id"])
            task = s["tasks"].get(c["task_id"])
            if any(x['stage_id'] == c['stage_id'] and x['status'] in {'START_INTENT','RUNNING','RECONCILE'}
                   for x in s['sessions'].values()):
                raise Conflict('cannot approve extension with an active or uncertain role')
            if (task is None or task["version"] != c["task_version"]
                    or candidate(c["repo"]) != c["candidate"]
                    or stage["budget"] != c["recorded_budget"]
                    or any(stage[k] != c["recorded_usage"][k] for k in c["recorded_usage"])):
                raise Conflict("stage, task, usage, or candidate changed since extension proposal")
            additional = c["additional_budget"]
            for key in ("role_calls", "wall_seconds", "fake_starts"):
                stage["budget"][key] += additional[key]
            stage["compute"]["limits"]["sol"] += c["additional_compute"]["sol"]
            stage["compute"]["limits"]["astra"] += c["additional_compute"]["astra"]
            stage.setdefault("approval_extensions", []).append(aid)
            task.update(status="QUEUED", next_role=c['next_role'], accepted_candidate=c["candidate"],
                        version=task["version"] + 1)
            task.pop("last_failure", None)
            task.pop("last_error", None)
        s["approvals"][aid] = {"approval_id": aid, "proposal_id": pid, "proposal_version": p["version"],
                              "proposal_sha256": digest, "decision": decision, "approver": "local-user-cli",
                              "time": time.time(), "reason": reason, "scope": c["scope"], "stage_id": c["stage_id"],
                              "budget": c.get("budget", c.get("additional_budget", c.get("package", {}).get("budget"))),
                              "preconditions": c.get("preconditions", ["exact extension binding"])}
        if decision == 'APPROVED' and c.get('execution', {}).get('mode') == 'stage_loop':
            from .engine import create_task
            tid = (create_task(s, store.root, c['stage_id'], c['task'])
                   if c['scope'] == 'STAGE' else c['task_id'])
            selected = s.setdefault('autonomous_tasks', [])
            if tid not in selected:
                selected.append(tid)
    return store.transact("APPROVAL_RECORDED", "decision:" + digest + ":" + decision, mutate, producer="user-cli", object_id=pid)
