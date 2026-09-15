"""Dispatch-time compute policy; consumed budgets live only in event state."""
import hashlib
from pathlib import Path
import yaml
from .contracts import ROLES
from .store import Conflict

POLICY = Path(__file__).resolve().parents[1] / 'model_policy.yaml'
TIERS = {'gpt-5.6-sol': 'sol', 'gpt-6-astra': 'astra'}


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    pairs = loader.construct_pairs(node, deep=deep)
    result = {}
    for key, value in pairs:
        if key in result:
            raise Conflict('duplicate model policy key')
        result[key] = value
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_policy(path=None):
    raw = Path(path or POLICY).read_bytes()
    try:
        p = yaml.load(raw, Loader=UniqueLoader)
        if set(p) != {'version', 'astra', 'roles'} or type(p['version']) is not int or p['version'] != 1:
            raise ValueError('version/keys')
        if (set(p['astra']) != {'enabled', 'max_calls_per_stage'} or type(p['astra']['enabled']) is not bool
                or type(p['astra']['max_calls_per_stage']) is not int or not 0 <= p['astra']['max_calls_per_stage'] <= 100):
            raise ValueError('Astra limits')
        if set(p['roles']) != set(ROLES):
            raise ValueError('six roles required')
        for role, steps in p['roles'].items():
            if not isinstance(steps, list) or not steps or len(steps) > 3:
                raise ValueError('steps')
            for i, step in enumerate(steps):
                if set(step) != {'model', 'effort'} or step['model'] not in TIERS or step['effort'] not in {'low', 'medium', 'high'}:
                    raise ValueError('model/effort')
                if role=='Scout' and step['effort']=='high':
                    raise ValueError('Scout escalation is limited to Sol medium')
                if step['model'] == 'gpt-6-astra':
                    if role == 'Scout' or not i or steps[i-1] != {'model': 'gpt-5.6-sol', 'effort': 'high'} or step['effort'] != 'high':
                        raise ValueError('Astra requires previous Sol high, forbidden for Scout')
                elif i and (steps[i-1]['model'] != 'gpt-5.6-sol' or ['low','medium','high'].index(step['effort']) <= ['low','medium','high'].index(steps[i-1]['effort'])):
                    raise ValueError('nonmonotonic escalation')
            if steps[0]['model'] != 'gpt-5.6-sol':
                raise ValueError('default must be Sol')
    except (yaml.YAMLError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise Conflict('invalid model policy: ' + str(exc)) from exc
    return {**p, 'sha256': hashlib.sha256(raw).hexdigest()}


def new_budget(calls):
    return {'limits': {'sol': calls, 'astra': 0}, 'used': {'sol': 0, 'astra': 0},
            'reserved_seconds': {'sol': 0, 'astra': 0}, 'used_seconds': {'sol': 0, 'astra': 0}}


def select(stage, role, policy=None, step=0):
    p = policy or load_policy()
    if type(step) is not int or not 0 <= step < len(p['roles'][role]):
        raise Conflict('model escalation step unavailable')
    choice = p['roles'][role][step]
    tier = TIERS[choice['model']]
    b = stage.get('compute')
    if not b:
        raise Conflict('legacy stage requires explicit compute-budget enrollment')
    if tier == 'astra' and not p['astra']['enabled']:
        raise Conflict('Astra disabled by policy')
    limit = b['limits'][tier]
    if tier == 'astra':
        limit = min(limit, p['astra']['max_calls_per_stage'])
    if b['used'][tier] + b.get('reserved_calls', {}).get(tier, 0) >= limit:
        raise Conflict(tier + ' compute budget exhausted')
    return {**choice, 'tier': tier, 'step': step, 'policy_version': p['version'], 'policy_sha256': p['sha256']}


def set_budget(store, sid, sol, astra, reason):
    from .policy import require_stage
    if any(type(n) is not int or n < 0 for n in (sol, astra)) or not reason.strip():
        raise Conflict('invalid model budget/reason')
    def change(s):
        stage = require_stage(s, sid)
        if any(x['stage_id'] == sid and x['status'] in {'START_INTENT','RUNNING','RECONCILE'} for x in s['sessions'].values()):
            raise Conflict('cannot change active compute budget')
        old = stage.get('compute')
        if old is None:
            if stage['used_calls'] != 0:
                raise Conflict('legacy consumption must be reconciled, never guessed or reset')
            old = stage['compute'] = new_budget(0)
        if sol + astra > stage['budget']['role_calls'] or any(v < old['used'][k] for k,v in [('sol',sol),('astra',astra)]):
            raise Conflict('compute allocation exceeds stage calls or drops recorded consumption')
        old['limits'] = {'sol':sol,'astra':astra}
        for task in s['tasks'].values():
            if task['stage_id']==sid and task['status']=='COMPUTE_BLOCKED':
                task.update(status='QUEUED',version=task['version']+1)
                task.pop('last_error',None)
        return {'limits':old['limits'],'reason':reason}
    import time
    return store.transact('COMPUTE_BUDGET_AUTHORIZED','compute-budget:'+sid+':'+str(time.time_ns()),change,producer='user-cli',object_id=sid)
