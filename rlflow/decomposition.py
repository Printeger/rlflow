"""PI decomposition inside an explicitly approved, bounded goal envelope."""
import json
from copy import deepcopy
from .store import Conflict, sha


def validate_policy(value):
    if not isinstance(value,dict) or set(value)!={'max_tasks','max_depth'}:
        raise Conflict('decomposition requires explicit task/depth limits')
    for key,upper in [('max_tasks',100),('max_depth',8)]:
        if type(value[key]) is not int or not 1<=value[key]<=upper:
            raise Conflict('invalid decomposition limit: '+key)


def parse(state,task,session,action,*,check_budget=True):
    if session['role']!='PI' or not task.get('package_id'):
        raise Conflict('only package PI may propose decomposition')
    package=state['packages'][task['package_id']];policy=package['spec'].get('decomposition')
    if not policy:raise Conflict('dynamic decomposition not approved')
    if task.get('children'):raise Conflict('parent already decomposed; refine an unfinished child instead')
    if task.get('depth',0)>=policy['max_depth']:raise Conflict('decomposition depth limit')
    if len(action['fields'])!=1 or len(action['fields'][0].encode())>32000:
        raise Conflict('one bounded decomposition object required')
    plan=json.loads(action['fields'][0])
    if not isinstance(plan,dict) or set(plan)!={'children'} or not isinstance(plan['children'],list) or not plan['children']:
        raise Conflict('decomposition needs nonempty children')
    if len(package['tasks'])+len(plan['children'])>policy['max_tasks']:
        raise Conflict('shared package task limit')
    if check_budget and package['spec'].get('schema_version')=='rlflow-package/2':
        from .governance import check_split
        check_split(state,task,len(plan['children']))
    criteria={c['id']:c for c in task['criteria']};seen=set();covered=set()
    for child in plan['children']:
        if not isinstance(child,dict) or (not {'id','text','depends_on','condition_ids'}<=set(child) or set(child)-{'id','text','depends_on','condition_ids','local_criteria'}):
            raise Conflict('child may only refine text, dependencies and existing conditions')
        if any(not isinstance(child[k],str) or not child[k].strip() for k in ('id','text')) or child['id'] in seen:
            raise Conflict('invalid child identity')
        seen.add(child['id'])
        for k in ('depends_on','condition_ids'):
            if not isinstance(child[k],list) or any(not isinstance(x,str) for x in child[k]) or len(set(child[k]))!=len(child[k]):
                raise Conflict('invalid child references')
        if not child['condition_ids'] or not set(child['condition_ids'])<=set(criteria):
            raise Conflict('child cannot create or weaken acceptance conditions')
        if 'local_criteria' in child:
            if package['spec'].get('schema_version')!='rlflow-package/2':raise Conflict('local criteria require package version 2')
            local=child['local_criteria']
            if not isinstance(local,list) or not local:raise Conflict('nonempty local criteria required')
            ids=set();parents=set()
            for c in local:
                if not isinstance(c,dict) or set(c)!={'id','description','layer','parent_condition_id'} or any(not isinstance(v,str) or not v for v in c.values()):raise Conflict('invalid local condition')
                parent=c['parent_condition_id']
                if parent not in child['condition_ids'] or c['layer']!=criteria[parent]['layer'] or c['id'] in ids:raise Conflict('local condition changes parent scope/layer')
                ids.add(c['id']);parents.add(parent)
            if parents!=set(child['condition_ids']):raise Conflict('local criteria must bind every assigned parent condition')
        covered.update(child['condition_ids'])
    if covered!=set(criteria):raise Conflict('decomposition must retain every parent condition')
    ready=set()
    while len(ready)<len(seen):
        addition={c['id'] for c in plan['children'] if c['id'] not in ready and set(c['depends_on'])<=ready}
        if not addition:raise Conflict('unknown or cyclic child dependencies')
        ready.update(addition)
    return plan


def apply(state,task,session,action):
    plan=parse(state,task,session,action);package=state['packages'][task['package_id']]
    from .engine import task_identity
    mapping={c['id']:task_identity(package['id'],c['text'],task['id']+'/'+c['id']) for c in plan['children']}
    if set(mapping.values())&set(state['tasks']):raise Conflict('duplicate dynamic child')
    record={'parent_id':task['id'],'session_id':session['id'],'plan':plan,'sha256':sha(plan),'children':list(mapping.values())}
    package.setdefault('decompositions',[]).append(record)
    conditions={c['id']:c for c in task['criteria']}
    for child in plan['children']:
        tid=mapping[child['id']]
        value={'id':tid,'version':1,'stage_id':task['stage_id'],'package_id':package['id'],'cycle_id':tid,
               'parent_id':task['id'],'depth':task.get('depth',0)+1,'text':child['text'],'repo':task['repo'],
               'baseline':deepcopy(task['baseline']),'accepted_candidate':deepcopy(task.get('accepted_candidate',task['baseline'])),
               'status':'QUEUED','next_role':'PI','repair_rounds':0,'diagnostic_after_rounds':3,
               'results':[],'findings':[],'consulted':[],'order':len(package['tasks']),
               'depends_on':[mapping[d] for d in child['depends_on']],
               'criteria':[deepcopy(conditions[c]) for c in child['condition_ids']],
               'research_mode':task.get('research_mode',False),'condition_evidence':{},
               'completion':dict.fromkeys(('implementation','cpu','real_run','behavior','formal'),False)}
        if 'local_criteria' in child:
            value['criteria']=[{k:v for k,v in c.items() if k!='parent_condition_id'} for c in child['local_criteria']]
            value['criterion_parents']={c['id']:c['parent_condition_id'] for c in child['local_criteria']}
        if task.get('input_contract'):
            value['input_contract']=deepcopy(task['input_contract']);value['route']=list(task['route']);value['next_role']=value['route'][0];value['final_integration']=False
        state['tasks'][tid]=value;package['tasks'].append(tid);state.setdefault('autonomous_tasks',[]).append(tid)
    task.update(children=list(mapping.values()),status='WAITING_CHILDREN',next_role='PI')


def verify(state,package,root_ids):
    expected=list(root_ids)
    for record in package.get('decompositions',[]):
        parent=state['tasks'].get(record['parent_id']);se=state['sessions'].get(record['session_id'],{})
        if not parent or parent['id'] not in expected or se.get('status')!='ACCEPTED' or se.get('role')!='PI' or se.get('task_id')!=parent['id']:
            raise Conflict('decomposition lacks accepted parent PI provenance')
        result=next((r for r in parent['results'] if r['session_id']==se['id']),{})
        actions=[a for a in result.get('requested_actions',[]) if a['action']=='REQUEST_DECOMPOSITION']
        if len(actions)!=1 or json.loads(actions[0]['fields'][0])!=record['plan'] or sha(record['plan'])!=record['sha256']:
            raise Conflict('decomposition source changed')
        shadow=deepcopy(parent);shadow.pop('children',None)
        # The full package task limit was enforced at creation; validate the
        # remaining immutable scope/dependency constraints without double counting.
        state_copy={**state,'packages':{package['id']:{**package,'tasks':expected}}}
        parse(state_copy,shadow,se,actions[0],check_budget=False)
        from .engine import task_identity
        mapping={c['id']:task_identity(package['id'],c['text'],parent['id']+'/'+c['id']) for c in record['plan']['children']}
        if record['children']!=list(mapping.values()) or parent.get('children')!=record['children']:
            raise Conflict('decomposition membership drifted')
        for child in record['plan']['children']:
            t=state['tasks'][mapping[child['id']]];conditions={c['id']:c for c in parent['criteria']}
            frozen={'parent_id':parent['id'],'depth':parent.get('depth',0)+1,'text':child['text'],
                    'stage_id':parent['stage_id'],'package_id':package['id'],'repo':parent['repo'],'baseline':parent['baseline'],
                    'criteria':[conditions[c] for c in child['condition_ids']],
                    'depends_on':[mapping[d] for d in child['depends_on']], 'research_mode':parent.get('research_mode',False)}
            if 'local_criteria' in child:
                frozen['criteria']=[{k:v for k,v in c.items() if k!='parent_condition_id'} for c in child['local_criteria']]
                frozen['criterion_parents']={c['id']:c['parent_condition_id'] for c in child['local_criteria']}
            if parent.get('input_contract'):frozen.update(input_contract=parent['input_contract'],route=parent['route'])
            if any(t.get(k)!=v for k,v in frozen.items()):raise Conflict('derived task contract drifted')
        expected.extend(record['children'])
    if package['tasks']!=expected:raise Conflict('unregistered package task')
