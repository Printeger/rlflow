"""Version-2 admission and controller-owned budget partitions."""
import math
from .store import Conflict


def route(task, policy):
    # Approval binds the permitted change classes and specification completeness;
    # roles never supply or lower the route used by the controller.
    high=task.get('research_mode',False) or any(c['layer']!='cpu' for c in task['criteria']) or policy['public_control'] or set(policy['change_categories'])!={'ENGINEERING_FIX'}
    if high:return ['PI','Critic','Engineer','Evaluator']
    return ['Engineer','Evaluator'] if policy['specification_complete'] else ['PI','Engineer','Evaluator']


def integration_route(spec):
    high=any('Critic' in route(task,spec['routing']) for task in spec['tasks'] if not task.get('final_integration'))
    return ['PI','Critic','Engineer','Evaluator'] if high else ['PI','Engineer','Evaluator']


def reserve_policy(spec):
    policy=spec.get('routing')
    if not isinstance(policy,dict) or set(policy)!={'public_control','change_categories','specification_complete'}:
        raise Conflict('routing requires approved scope and specification completeness')
    if type(policy['public_control']) is not bool or type(policy['specification_complete']) is not bool or not isinstance(policy['change_categories'],list) or not policy['change_categories']:
        raise Conflict('invalid routing policy')
    if set(policy['change_categories'])-{'ENGINEERING_FIX','METHOD_CHANGE','EVALUATION_CHANGE','RUNTIME_CHANGE','RESOURCE_CHANGE'}:
        raise Conflict('unknown approved change class')
    calls=spec['budget']['role_calls'];seconds=spec['budget']['wall_seconds'];limit=spec['per_call_seconds']
    integration=max(len(integration_route(spec)),math.ceil(calls*.2));recovery=max(2,math.ceil(calls*.1))
    integration_seconds=max(math.ceil(seconds*.2),integration*limit)
    recovery_seconds=max(math.ceil(seconds*.1),recovery*limit)
    required=sum(len(route(task,policy)) for task in spec['tasks'])
    if calls<required+integration+recovery or seconds<required*limit+integration_seconds+recovery_seconds:
        raise Conflict(f'budget cannot cover minimum route plus reserves: need {required+integration+recovery} calls and {required*limit+integration_seconds+recovery_seconds} seconds')
    result={'ordinary':{'calls':calls-integration-recovery,'seconds':seconds-integration_seconds-recovery_seconds},
            'integration':{'calls':integration,'seconds':integration_seconds},
            'recovery':{'calls':recovery,'seconds':recovery_seconds}}
    if 'budget_reserves' in spec and spec['budget_reserves']!=result:raise Conflict('reserve allocation differs from approved calculation')
    return result


def pool(task):
    if task.get('recovery_source') or task.get('repair_id'):return 'recovery'
    if task.get('integration_review') or task.get('final_integration'):return 'integration'
    return 'ordinary'


def remaining(stage, task):
    if 'budget_reserves' not in stage:return None
    name=pool(task);limit=stage['budget_reserves'][name];usage=stage.get('pool_usage',{}).get(name,{})
    return {'pool':name,'role_calls':limit['calls']-usage.get('used_calls',0)-usage.get('reserved_calls',0),
            'wall_seconds':limit['seconds']-usage.get('used_seconds',0)-usage.get('reserved_seconds',0)}


def reserve(stage,session,task):
    balance=remaining(stage,task)
    if balance is None:return
    if balance['role_calls']<1 or balance['wall_seconds']<session['limit']:raise Conflict('budget reserve pool unavailable')
    if balance['pool']=='recovery' and not task.get('recovery_source') and not task.get('repair_id'):
        raise Conflict('recovery pool requires failure provenance')
    usage=stage.setdefault('pool_usage',{}).setdefault(balance['pool'],{'used_calls':0,'used_seconds':0,'reserved_calls':0,'reserved_seconds':0})
    usage['reserved_calls']+=1;usage['reserved_seconds']+=session['limit'];session['budget_pool']=balance['pool']


def settle(stage,session,receipt):
    if 'budget_pool' not in session:return
    outcome=receipt.get('model_usage',{}).get('state','UNKNOWN')
    if outcome=='UNKNOWN':return
    usage=stage['pool_usage'][session['budget_pool']]
    usage['reserved_calls']-=1;usage['reserved_seconds']-=session['limit']
    if outcome=='USED':
        usage['used_calls']+=1;usage['used_seconds']+=receipt.get('model_active_seconds',receipt['elapsed_seconds'])


def check_split(state,task,count):
    stage=state['stages'][task['stage_id']]
    balance=remaining(stage,task)
    if balance is None:return
    policy=state['packages'][task['package_id']]['spec']['routing']
    # Children inherit the parent's route. Each decomposition level also needs
    # an independent integration path, charged against the reserved pool.
    minimum=count*len(route(task,policy))
    integration=remaining(stage,{'integration_review':True})
    outstanding=sum(max(3,len(t.get('route',[]))) for t in state['tasks'].values() if t['stage_id']==task['stage_id'] and t['status']!='DONE' and (t.get('final_integration') or t.get('children')))
    integration_calls=outstanding+max(3,len(task.get('route',[])))
    if balance['role_calls']<minimum or balance['wall_seconds']<minimum*stage['per_call_seconds'] or integration['role_calls']<integration_calls or integration['wall_seconds']<integration_calls*stage['per_call_seconds']:
        raise Conflict('decomposition would consume the minimum execution/integration path')
