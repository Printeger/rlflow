"""Explicit, hash-bound work packages. Legacy stages never gain package authority."""
from copy import deepcopy
from pathlib import Path
import time
from .store import Conflict, sha, atomic, canonical
from .policy import candidate, new_stage, require_stage, _validated_candidate_paths


def validate(spec, root):
    spec = deepcopy(spec)
    required = {'id', 'goal', 'repo', 'module_roots', 'protected_paths', 'tasks', 'budget'}
    if not required <= spec.keys() or set(spec) - required - {'schema_version', 'per_call_seconds', 'command_seconds', 'scout_sources', 'experiments', 'decomposition', 'parameter_search', 'control_release'}:
        raise Conflict('invalid work package fields')
    if spec.get('schema_version', 'rlflow-package/1') != 'rlflow-package/1':
        raise Conflict('unsupported package version')
    spec['schema_version'] = 'rlflow-package/1'
    if 'control_release' in spec:
        from .verification import code_identity
        if spec['control_release']!=code_identity():raise Conflict('package requires a different exact control release')
    if any(not isinstance(spec[k], str) or not spec[k].strip() for k in ('id', 'goal', 'repo')):
        raise Conflict('package identity and goal required')
    repo = Path(spec['repo']).resolve(strict=True)
    if not repo.is_relative_to(Path(root) / 'workspaces'):
        raise Conflict('package repository must be isolated')
    spec['repo'] = str(repo)
    spec['module_roots'], spec['protected_paths'] = _validated_candidate_paths(repo, spec['module_roots'], spec['protected_paths'])
    budget = spec['budget']
    if not isinstance(budget, dict) or set(budget) - {'role_calls', 'wall_seconds', 'fake_starts'}:
        raise Conflict('invalid resource pool')
    calls = budget.get('role_calls')
    if type(calls) is not int or not 1 <= calls <= 100:
        raise Conflict('invalid role call budget')
    budget.setdefault('wall_seconds', calls * 3600)
    budget.setdefault('fake_starts', 0)
    for field, limit in (('wall_seconds', 360000), ('fake_starts', 100)):
        if type(budget[field]) is not int or not (0 if field == 'fake_starts' else 1) <= budget[field] <= limit:
            raise Conflict('invalid package budget: ' + field)
    for field, default in (('per_call_seconds', 3600), ('command_seconds', 1800)):
        spec.setdefault(field, default)
        if type(spec[field]) is not int or not 1 <= spec[field] <= default:
            raise Conflict('invalid package time limit')
    if spec.get('scout_sources',[]) not in ([], ['arxiv']):
        raise Conflict('unsupported controlled literature provider')
    searches=spec.get('parameter_search',[])
    if not isinstance(searches,list) or len(searches)>10:raise Conflict('invalid parameter search families')
    if searches:
        from .search import expand
        existing={e['id']:e for e in spec.get('experiments',[])}
        for family in searches:
            for trial,_ in expand(family):
                if trial['id'] in existing and existing[trial['id']]!=trial:raise Conflict('search trial identity collision')
                existing[trial['id']]=trial
        spec['experiments']=list(existing.values())
    experiments=spec.get('experiments',[])
    if not isinstance(experiments,list) or len(experiments)>100 or len({e.get('id') for e in experiments})!=len(experiments):
        raise Conflict('invalid package experiment list')
    from .experiments import validate as validate_experiment
    for experiment in experiments:
        validate_experiment(experiment,root)
        if experiment['stage_id']!=spec['id']:raise Conflict('experiment must belong to this package')
    if 'decomposition' in spec:
        from .decomposition import validate_policy
        validate_policy(spec['decomposition'])
        if len(spec['tasks'])>spec['decomposition']['max_tasks']:raise Conflict('initial task count exceeds decomposition envelope')
    tasks = spec['tasks']
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 100:
        raise Conflict('package needs 1..100 tasks')
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or not {'id', 'text', 'depends_on', 'criteria'} <= set(task) or set(task) - {'id', 'text', 'depends_on', 'criteria', 'research_mode'}:
            raise Conflict('task needs id, text, depends_on and criteria')
        if any(not isinstance(task[k], str) or not task[k].strip() for k in ('id', 'text')) or task['id'] in seen:
            raise Conflict('invalid/duplicate task identity')
        seen.add(task['id'])
        if 'research_mode' in task and type(task['research_mode']) is not bool:raise Conflict('research_mode must be boolean')
        if not isinstance(task['depends_on'], list) or any(not isinstance(d, str) for d in task['depends_on']):
            raise Conflict('invalid dependencies')
        criteria = task['criteria']
        if not isinstance(criteria, list) or not criteria:
            raise Conflict('explicit acceptance criteria required')
        ids = set()
        for c in criteria:
            if (not isinstance(c, dict) or set(c) != {'id', 'description', 'layer'}
                    or c['layer'] not in {'cpu', 'real_run', 'behavior', 'formal'}
                    or any(not isinstance(c[k], str) or not c[k].strip() for k in c)
                    or c['id'] in ids):
                raise Conflict('invalid acceptance condition')
            ids.add(c['id'])
    done = set()
    while len(done) < len(tasks):
        ready = {t['id'] for t in tasks if t['id'] not in done and set(t['depends_on']) <= done}
        if not ready:
            raise Conflict('unknown or cyclic task dependencies')
        done |= ready
    return spec


def propose(store, spec):
    spec = validate(spec, store.root)
    content = {'schema_version': 'rlflow-proposal/2', 'scope': 'PACKAGE', 'stage_id': spec['id'],
               'package': spec, 'baseline': candidate(spec['repo']),
               'execution': {'mode': 'package', 'start_on_approval': True},
               'authority': 'CPU engineering only; each higher evidence layer requires separate exact authorization'}
    digest = sha(content)
    pid = 'P-' + digest[:16]
    def change(s):
        if spec['id'] in s['stages']:
            raise Conflict('stage exists; no automatic budget transfer or reset')
        # Identity and prose cannot launder a rejected proposal into fresh authority.
        scope = sha({k: spec[k] for k in ('repo', 'module_roots', 'protected_paths', 'budget')})
        for a in s['approvals'].values():
            old = s['proposals'][a['proposal_id']]['content']
            if a['decision'] == 'REJECTED' and old.get('scope_fingerprint') == scope:
                raise Conflict('rejected scope requires independently verified new evidence')
        s['proposals'][pid] = {'id': pid, 'version': 1, 'sha256': digest, 'content': content, 'shown': False}
    # Fingerprint is part of the exact displayed proposal.
    content['scope_fingerprint'] = sha({k: spec[k] for k in ('repo', 'module_roots', 'protected_paths', 'budget')})
    digest = sha(content); pid = 'P-' + digest[:16]
    store.transact('PROPOSAL_CREATED', 'proposal:' + digest, change, object_id=pid)
    atomic(store.root / 'proposals' / (pid + '.json'), canonical(content))
    return pid


def approve_in(s, content, aid, digest):
    from .model_policy import new_budget
    spec = content['package']; pid = spec['id']
    if 'control_release' in spec:
        from .verification import code_identity
        if spec['control_release']!=code_identity():raise Conflict('control release changed before approval')
    if pid in s['stages'] or candidate(spec['repo']) != content['baseline']:
        raise Conflict('package stage exists or candidate drifted')
    # Build legacy-compatible stage; larger package pool is explicit approved content.
    small = {**spec['budget'], 'wall_seconds': min(86400, spec['budget']['wall_seconds'])}
    stage = new_stage(pid, spec['repo'], spec['goal'], small, digest, approval_id=aid,
                      module_roots=spec['module_roots'], protected_paths=spec['protected_paths'])
    stage.update(budget=spec['budget'], package_id=pid, per_call_seconds=spec['per_call_seconds'],
                 command_seconds=spec['command_seconds'], reserved_calls=0)
    s['stages'][pid] = stage
    package = {'id': pid, 'version': 1, 'spec': spec, 'approval_id': aid, 'status': 'ACTIVE',
               'paused': False, 'tasks': [], 'achievements': {}, 'next_actions': []}
    s.setdefault('packages', {})[pid] = package
    s.setdefault('goals', {})[pid] = {'id': pid, 'description': spec['goal'], 'package_id': pid, 'status': 'ACTIVE'}
    from .engine import task_identity
    mapping = {t['id']: task_identity(pid, t['text'], t['id']) for t in spec['tasks']}
    for index, item in enumerate(spec['tasks']):
        tid = mapping[item['id']]
        s['tasks'][tid] = {'id': tid, 'version': 1, 'stage_id': pid, 'package_id': pid, 'cycle_id': tid,
            'text': item['text'], 'repo': spec['repo'], 'baseline': content['baseline'],
            'status': 'QUEUED', 'next_role': 'PI', 'repair_rounds': 0, 'diagnostic_after_rounds': 3,
            'results': [], 'findings': [], 'consulted': [], 'order': index,
            'depends_on': [mapping[d] for d in item['depends_on']], 'criteria': item['criteria'], 'research_mode': item.get('research_mode',False),
            'condition_evidence': {}, 'completion': dict.fromkeys(('implementation', 'cpu', 'real_run', 'behavior', 'formal'), False)}
        package['tasks'].append(tid)
        s.setdefault('autonomous_tasks', []).append(tid)
    refresh(s, pid)


def require_package(s, stage):
    p = s.get('packages', {}).get(stage.get('package_id'))
    if not p:
        raise Conflict('missing package')
    a = s['approvals'].get(p['approval_id'], {})
    proposal = s['proposals'].get(a.get('proposal_id'), {})
    c = proposal.get('content', {})
    if (a.get('decision') != 'APPROVED' or a.get('revoked') or proposal.get('revoked')
            or c.get('scope') != 'PACKAGE' or c.get('package') != p['spec']
            or sha(c) != a.get('proposal_sha256') or sha(c) != proposal.get('sha256')
            or a.get('proposal_version') != proposal.get('version') or stage['authorization'] != sha(c)):
        raise Conflict('package approval invalid/revoked/drifted')
    spec = p['spec']
    if 'control_release' in spec:
        from .verification import code_identity
        if spec['control_release']!=code_identity():raise Conflict('package bound control release changed')
    for field in ('repo', 'module_roots', 'protected_paths', 'budget', 'per_call_seconds', 'command_seconds'):
        if stage.get(field) != spec[field]:
            raise Conflict('package scope or limits drifted: ' + field)
    if stage['categories'] != ['ENGINEERING_FIX'] or stage['scope'] != spec['goal'] or stage.get('cpu_runtime') is not None:
        raise Conflict('package permissions drifted')
    from .engine import task_identity
    mapping={item['id']:task_identity(spec['id'],item['text'],item['id']) for item in spec['tasks']}
    from .decomposition import verify
    verify(s,p,list(mapping.values()))
    for item in spec['tasks']:
        task=s['tasks'][mapping[item['id']]]
        if (task['criteria']!=item['criteria'] or task['text']!=item['text'] or task['repo']!=spec['repo'] or task['baseline']!=c['baseline']
                or task['depends_on']!=[mapping[d] for d in item['depends_on']]
                or task.get('research_mode',False)!=item.get('research_mode',False)):
            raise Conflict('approved task scope or conditions drifted')
    return p


def runnable(s, task):
    if task.get('repair_id'):
        parent=s['repairs'][task['repair_id']]['stage_id']
        package=s.get('packages',{}).get(parent,{})
        return package.get('status')=='ACTIVE' and not package.get('paused',True)
    pid = task.get('package_id')
    if not pid:
        return True
    p = s['packages'][pid]
    return p['status'] == 'ACTIVE' and not p['paused'] and all(s['tasks'][d]['status'] == 'DONE' for d in task['depends_on'])


def refresh(s, pid):
    p = s['packages'][pid]
    tasks = [s['tasks'][tid] for tid in p['tasks']]
    for task in reversed(tasks):
        if task['status']=='WAITING_CHILDREN' and all(s['tasks'][tid]['status']=='DONE' for tid in task['children']):
            task.update(status='QUEUED',next_role='PI',integration_review=True,accepted_candidate=deepcopy(p.get('accepted_candidate',task.get('accepted_candidate',task['baseline']))))
            task['version']+=1
            if not p['paused'] and task['id'] not in s.setdefault('autonomous_tasks',[]):s['autonomous_tasks'].append(task['id'])
    p['next_actions'] = [{'task_id': t['id'], 'role': t['next_role'],
                          'blocked_by': [d for d in t['depends_on']+t.get('children',[]) if s['tasks'][d]['status'] != 'DONE'],
                          'status': t['status']} for t in tasks if t['status'] != 'DONE']
    if all(t['status'] == 'DONE' for t in tasks):
        p['status'] = 'DONE'; s['goals'][pid]['status'] = 'DONE'; s['stages'][pid]['status'] = 'HOLD'
        s['autonomous_tasks'] = [tid for tid in s.get('autonomous_tasks', []) if tid not in p['tasks']]


def cpu_complete(s, task, evidence_id, candidate_value):
    """Only independently covered frozen conditions close a package task."""
    p = s['packages'][task['package_id']]
    result = task['results'][-1]['payload']
    coverage = set(result['evidence_coverage'])
    for condition in task['criteria']:
        if condition['layer'] == 'cpu' and condition['id'] in coverage:
            task['condition_evidence'][condition['id']] = evidence_id
    complete = all(c['id'] in task['condition_evidence'] for c in task['criteria'])
    task['status'] = 'DONE' if complete else 'CONTRACT_DECISION'
    if not complete:
        task['last_error'] = 'required condition evidence missing or higher-layer authorization required'
    p['achievements'][task['id']] = deepcopy(task['condition_evidence'])
    p['accepted_candidate']=deepcopy(candidate_value)
    # Shared repository edits are accepted only through this verified candidate boundary.
    # All tasks retain the package baseline for cumulative independent classification.
    for tid in p['tasks']:
        other = s['tasks'][tid]
        if other['status'] == 'QUEUED':
            other['accepted_candidate'] = candidate_value
    refresh(s, p['id'])


def pause(store, pid, paused):
    def change(s):
        p = s['packages'][pid]
        if not paused:
            require_stage(s, pid)
            if any(x['status'] in {'START_INTENT', 'RUNNING', 'RECONCILE'} for x in s['sessions'].values()):
                raise Conflict('reconcile active/uncertain sessions before package resume')
            from .policy import stopped
            if stopped(store.root): raise Conflict('STOP')
        p['paused'] = paused
        selected = s.setdefault('autonomous_tasks', [])
        related=p['tasks']+[r['task_id'] for r in s.get('repairs',{}).values() if r['stage_id']==pid and r.get('task_id')]
        s['autonomous_tasks'] = [t for t in selected if t not in related]
        if not paused: s['autonomous_tasks'] += [t for t in related if s['tasks'][t]['status'] == 'QUEUED']
    return store.transact('PACKAGE_PAUSED' if paused else 'PACKAGE_RESUMED', f'package-pause:{pid}:{time.time_ns()}', change, object_id=pid, producer='user-cli')


def from_goal(value):
    """A user supplies outcomes and boundaries, PI supplies the work breakdown."""
    value=deepcopy(value)
    required={'id','goal','repo','module_roots','protected_paths','criteria','budget'}
    optional={'decomposition','research_mode','per_call_seconds','command_seconds','scout_sources','experiments','parameter_search'}
    if not isinstance(value,dict) or not required<=set(value) or set(value)-required-optional:
        raise Conflict('goal needs explicit criteria, repository scope and total budget')
    conditions=value.pop('criteria');research=value.pop('research_mode',False)
    value.setdefault('decomposition',{'max_tasks':32,'max_depth':4})
    value['tasks']=[{'id':'goal','text':value['goal'],'depends_on':[],'criteria':conditions,'research_mode':research}]
    return value
