"""Explicit, hash-bound work packages. Legacy stages never gain package authority."""
from copy import deepcopy
from pathlib import Path
import time
from .store import Conflict, sha, atomic, canonical
from .policy import candidate, new_stage, require_stage, _validated_candidate_paths


def _compatible_control_release(state, current, target):
    """Return whether validated release metadata links current back to target."""
    pending = [current]
    seen = set()
    while pending:
        release_id = pending.pop()
        if release_id == target:
            return True
        if release_id in seen:
            continue
        seen.add(release_id)
        validation = state.get('releases', {}).get(release_id, {}).get('validation', {})
        parents = validation.get('compatible_from')
        if (validation.get('exit_code') != 0
                or validation.get('isolated_state') is not True
                or validation.get('code_identity') != release_id
                or validation.get('compatibility_scope') != 'PACKAGE_EXTENSION_VALIDATION_ONLY'
                or type(parents) is not list
                or any(type(item) is not str for item in parents)):
            continue
        pending.extend(parents)
    return False


def input_contract(spec):
    if spec.get('schema_version')!='rlflow-package/2':return None
    return {'manifest':spec['inputs'],'module_roots':spec['module_roots'],'protected_paths':spec['protected_paths']}


def validate(spec, root):
    spec = deepcopy(spec)
    required = {'id', 'goal', 'repo', 'module_roots', 'protected_paths', 'tasks', 'budget'}
    if not required <= spec.keys() or set(spec) - required - {'schema_version', 'per_call_seconds', 'command_seconds', 'scout_sources', 'experiments', 'decomposition', 'parameter_search', 'control_release', 'inputs', 'resource_policy', 'routing', 'budget_reserves', 'usage_policy'}:
        raise Conflict('invalid work package fields')
    if spec.get('schema_version', 'rlflow-package/1') not in {'rlflow-package/1','rlflow-package/2'}:
        raise Conflict('unsupported package version')
    spec.setdefault('schema_version','rlflow-package/1')
    if spec['schema_version']=='rlflow-package/1' and any(k in spec for k in ('inputs','resource_policy','routing','budget_reserves','usage_policy')):
        raise Conflict('new governance fields require package version 2')
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
    if spec['schema_version']=='rlflow-package/2':
        from .files import validate_inputs
        from .resources import validate_policy
        from .governance import reserve_policy
        validate_inputs(spec.get('inputs'),spec['module_roots'],spec['protected_paths'])
        validate_policy(spec.get('resource_policy'))
        if 'usage_policy' in spec:
            from .usage import validate_policy as validate_usage_policy
            validate_usage_policy(spec['usage_policy'])
        spec['budget_reserves']=reserve_policy(spec)
        if any(t['id']=='__final_integration__' for t in spec['tasks']):raise Conflict('reserved integration task identity')
        spec['tasks'].append({'id':'__final_integration__','text':'Independently integrate the final cumulative candidate against all original conditions and interactions: '+spec['goal'],
            'depends_on':[t['id'] for t in spec['tasks']],
            'criteria':[dict(c,id=t['id']+':'+c['id']) for t in spec['tasks'] for c in t['criteria']],
            'final_integration':True})
    return spec


def propose(store, spec):
    spec = validate(spec, store.root)
    if input_contract(spec):
        from .files import verify_data,verify_environment
        verify_data(spec['repo'],spec['inputs'])
        verify_environment(spec['inputs']['environment'])
    content = {'schema_version': 'rlflow-proposal/2', 'scope': 'PACKAGE', 'stage_id': spec['id'],
               'package': spec, 'baseline': candidate(spec['repo'],input_contract(spec)),
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
    if pid in s['stages'] or candidate(spec['repo'],input_contract(spec)) != content['baseline']:
        raise Conflict('package stage exists or candidate drifted')
    # Build legacy-compatible stage; larger package pool is explicit approved content.
    small = {**spec['budget'], 'wall_seconds': min(86400, spec['budget']['wall_seconds'])}
    stage = new_stage(pid, spec['repo'], spec['goal'], small, digest, approval_id=aid,
                      module_roots=spec['module_roots'], protected_paths=spec['protected_paths'],input_contract=input_contract(spec))
    stage.update(budget=spec['budget'], package_id=pid, per_call_seconds=spec['per_call_seconds'],
                 command_seconds=spec['command_seconds'], reserved_calls=0)
    if spec['schema_version']=='rlflow-package/2':
        stage.update(budget_reserves=spec['budget_reserves'],routing=spec['routing'],resource_policy=spec['resource_policy'],input_contract=input_contract(spec))
    if 'usage_policy' in spec:stage['usage_policy']=spec['usage_policy']
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
        if spec['schema_version']=='rlflow-package/2':
            s['tasks'][tid]['input_contract']=input_contract(spec)
            from .governance import route,integration_route
            s['tasks'][tid]['route']=integration_route(spec) if item.get('final_integration') else route(item,spec['routing'])
            s['tasks'][tid]['final_integration']=item.get('final_integration',False)
            s['tasks'][tid]['next_role']=s['tasks'][tid]['route'][0]
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
        current = code_identity()
        if spec['control_release'] != current:
            if not _compatible_control_release(s, current, spec['control_release']):
                raise Conflict('package bound control release changed')
    expected_budget = dict(spec['budget'])
    extensions = stage.get('approval_extensions', [])
    if len(extensions) != len(set(extensions)):
        raise Conflict('duplicate package extension approval')
    for extension_id in extensions:
        extension = s['approvals'].get(extension_id, {})
        extension_proposal = s['proposals'].get(extension.get('proposal_id'), {})
        extension_content = extension_proposal.get('content', {})
        if (extension.get('decision') != 'APPROVED' or extension.get('revoked')
                or extension_proposal.get('revoked')
                or extension_content.get('scope') != 'STAGE_EXTENSION'
                or extension_content.get('stage_id') != stage['id']
                or extension_content.get('recorded_budget') != expected_budget
                or sha(extension_content) != extension.get('proposal_sha256')
                or sha(extension_content) != extension_proposal.get('sha256')
                or extension.get('proposal_version') != extension_proposal.get('version')):
            raise Conflict('package extension approval invalid')
        additional = extension_content.get('additional_budget', {})
        for key in ('role_calls', 'wall_seconds', 'fake_starts'):
            value = additional.get(key)
            if type(value) is not int or value < 0:
                raise Conflict('package extension budget invalid')
            expected_budget[key] += value
    if spec['schema_version']=='rlflow-package/2':
        from .files import verify_data,verify_environment
        verify_data(spec['repo'],spec['inputs'])
        verify_environment(spec['inputs']['environment'])
        if stage.get('input_contract')!=input_contract(spec):raise Conflict('input contract drift')
        for field in ('budget_reserves','resource_policy','routing'):
            if stage.get(field)!=spec[field]:raise Conflict('package governance drift: '+field)
    for field in ('repo', 'module_roots', 'protected_paths', 'per_call_seconds', 'command_seconds'):
        if stage.get(field) != spec[field]:
            raise Conflict('package scope or limits drifted: ' + field)
    if stage.get('usage_policy')!=spec.get('usage_policy'):raise Conflict('usage admission policy drift')
    if stage.get('budget') != expected_budget:
        raise Conflict('package scope or limits drifted: budget')
    if stage['categories'] != ['ENGINEERING_FIX'] or stage['scope'] != spec['goal'] or stage.get('cpu_runtime') is not None:
        raise Conflict('package permissions drifted')
    from .engine import task_identity
    mapping={item['id']:task_identity(spec['id'],item['text'],item['id']) for item in spec['tasks']}
    from .decomposition import verify
    verify(s,p,list(mapping.values()))
    for item in spec['tasks']:
        task=s['tasks'][mapping[item['id']]]
        if spec['schema_version']=='rlflow-package/2':
            from .governance import route,integration_route
            if task.get('input_contract')!=input_contract(spec) or task.get('route')!=(integration_route(spec) if item.get('final_integration') else route(item,spec['routing'])) or task.get('final_integration')!=item.get('final_integration',False):raise Conflict('task input/routing drift')
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
