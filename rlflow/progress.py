"""Evidence-driven condition tracking; report names and candidate hashes do not count."""
from .store import Conflict, sha


def review(state, task, payload):
    package = state.setdefault('research', {}).setdefault(task.get('package_id', task['stage_id']), {})
    registry = package.setdefault('findings', {})
    conditions = {c['id'] for c in task.get('criteria', [])}
    old = set(task.get('open_problem_keys', [])); current = set(); new_information = False; previously_seen = False
    for finding in payload['findings']:
        if finding['category'] != 'MUST_FIX': continue
        if task.get('package_id') and (not finding['evidence_refs'] or any(not finding[k].strip() for k in ('contract', 'affected_conclusion', 'close_condition'))):
            raise Conflict('MUST_FIX requires contract, evidence, impact and closure')
        # Exact approved condition names are stable. Unknown associations share a
        # diagnostic bucket: prose/ID changes cannot establish a new problem.
        condition = finding['contract'] if finding['contract'] in conditions else 'UNRESOLVED_CONTRACT_ASSOCIATION'
        key = sha({'package': task.get('package_id', task['stage_id']), 'condition': condition})
        evidence = {state['evidence'][eid]['sha256'] for eid in finding['evidence_refs'] if eid in state['evidence']}
        previously_seen |= key in registry
        record = registry.setdefault(key, {'condition': condition, 'evidence': [], 'aliases': [], 'closed': False})
        novel = evidence - set(record['evidence'])
        # Only explicit verified relevance can establish material information;
        # a new role report is not an independent discriminating observation.
        material = any(state['evidence'][eid].get('verified_condition') == condition
                       and state['evidence'][eid].get('material_observation')
                       and state['evidence'][eid]['sha256'] in novel for eid in finding['evidence_refs'])
        if record['closed'] and not material:
            raise Conflict('closed condition requires new material evidence to reopen')
        record['closed'] = False
        record['evidence'] = sorted(set(record['evidence']) | evidence)
        record['aliases'] = sorted(set(record['aliases']) | {finding['id']})
        current.add(key); new_information |= material
    for key in old - current:
        if key in registry:
            registry[key]['closed'] = True
    task['open_problem_keys'] = sorted(current)
    closed = bool(old - current)
    progress = closed or new_information
    task['no_progress_rounds'] = 0 if progress else task.get('no_progress_rounds', 0) + 1
    diagnostic = (bool(current & old) or previously_seen) and not new_information or task['no_progress_rounds'] >= 3
    task['progress'] = {'closed_condition': closed, 'material_new_evidence': new_information,
                        'diagnostic_required': diagnostic}
    if diagnostic: task['continuation_requires_evidence'] = True
    return diagnostic


def continuation(state, task, payload):
    if not task.get('continuation_requires_evidence'): return True
    if not payload.get('next_prediction', '').strip(): return False
    known = {h for record in state.get('research', {}).get(task.get('package_id', task['stage_id']), {}).get('findings', {}).values() for h in record['evidence']}
    for observation in payload.get('observations', []):
        for eid in observation['evidence_refs']:
            e = state['evidence'][eid]
            if e.get('material_observation') and e.get('verified_condition') and e['sha256'] not in known:
                task.pop('continuation_requires_evidence', None)
                return True
    # A proposed discriminating test needs independent validation before reuse.
    return False


def verify_observations(state, task, session, payload):
    """Independent evaluator binds material observations to immutable job evidence.

    Coverage entries use OBSERVATION:<JSON> with condition_id, evidence_id,
    evidence_sha256 and explanation. Report IDs, test counts and new commits
    alone never become observations.
    """
    import json
    if session['role'] != 'Evaluator': raise Conflict('only independent evaluation verifies observations')
    conditions={c['id'] for c in task.get('criteria',[])}
    for text in payload['evidence_coverage']:
        if not text.startswith('OBSERVATION:'): continue
        try: proof=json.loads(text[len('OBSERVATION:'):])
        except ValueError as exc: raise Conflict('invalid material observation') from exc
        if set(proof)!={'condition_id','evidence_id','evidence_sha256','explanation'} or proof['condition_id'] not in conditions or not proof['explanation'].strip():
            raise Conflict('observation lacks frozen condition or independent explanation')
        e=state['evidence'].get(proof['evidence_id'],{})
        if not e.get('job_id') or not e.get('accepted') or e.get('sha256')!=proof['evidence_sha256'] or e.get('task_id')!=task['id']:
            raise Conflict('material observation must bind this task immutable raw job evidence')
        e['verified_conditions']=sorted(set(e.get('verified_conditions',[]))|{proof['condition_id']})
        e.update(verified_condition=proof['condition_id'],material_observation=True,
                 independent_verifier=session['id'],explanation=proof['explanation'])
