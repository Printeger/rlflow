"""Research transitions executed by the sole dispatcher, never by role prose."""
from .store import Conflict, sha


def record(state, task):
    root = state.setdefault('research', {}).setdefault(task.get('package_id', task['stage_id']), {})
    return root.setdefault('cycles', {}).setdefault(task['id'], {'id': task['id'], 'question': task['text'],
        'hypotheses': [], 'experiments': [], 'valid_cycles': 0, 'phase': 'QUESTION', 'scout_cycles': [], 'negative_results': []})


def route(state, task, session, result):
    """Return true when a research route owns this transition."""
    if not task.get('research_mode'): return False
    cycle=record(state,task);payload=result['payload'];role=session['role']
    if role=='PI':
        decision=payload['decision']
        if any(a['action'] in {'REQUEST_COMPLETE','REQUEST_DECOMPOSITION'} for a in result['requested_actions']):
            if decision=='STOP' or payload['proposal_required']:raise Conflict('terminal/proposal PI cannot execute goal actions')
            return True
        if decision=='STOP':
            task['status']='STOPPED';cycle['phase']='STOPPED';return True
        if not payload['next_prediction'].strip():
            raise Conflict('research continuation requires a discriminating prediction')
        cycle['prediction']=payload['next_prediction']
        if payload['proposal_required']:
            task.update(status='CONTRACT_DECISION',proposal_request=payload);return True
        if cycle.get('cold_due'):
            task.update(next_role='Evaluator',cold_review='RAW');cycle['phase']='COLD_RAW';return True
        if decision in {'METHOD_REVIEW','EVALUATION_REVIEW'}:
            # Authorized read-only analysis produces proposals; does not change contracts.
            task.update(next_role='Critic',review_kind=decision);cycle['phase']='METHOD_ANALYSIS';return True
        if decision=='ENGINEERING_DIAGNOSIS':
            task['next_role']='Engineer';cycle['phase']='ENGINEERING';return True
        if decision in {'CONTINUE','PARAMETER_SEARCH'}:
            task['next_role']='Designer' if cycle['hypotheses'] else 'Critic'
            cycle['phase']='DESIGN' if cycle['hypotheses'] else 'HYPOTHESES';return True
    elif role=='Critic':
        if not 1<=len(payload['hypotheses'])<=3:raise Conflict('research requires 1..3 hypotheses')
        cycle.setdefault('hypothesis_history',[]).extend(cycle['hypotheses'])
        cycle['hypotheses']=[{'id':'H-'+sha(h)[:16],**h,'status':'ACTIVE'} for h in payload['hypotheses']]
        task['next_role']='PI';cycle['phase']='FRESH_PI';return True
    elif role=='Designer':
        if not payload['required_observations'] or not payload['decision_rules'] or not payload['stop_conditions']:
            raise Conflict('design lacks required observations, rules or stop conditions')
        cycle['design']=payload
        actions=[a for a in result['requested_actions'] if a['action']=='REQUEST_EXPERIMENT']
        if len(actions)!=1 or len(actions[0]['fields'])!=1:
            task.update(status='CONTRACT_DECISION',last_error='design must reference one exact approved experiment specification')
        else:
            task.update(status='WAITING_EXPERIMENT',experiment_request=actions[0]['fields'][0])
            cycle['phase']='EXPERIMENT'
        return True
    elif role=='Evaluator' and task.get('cold_review'):
        if task['cold_review']=='RAW':
            cycle['cold_raw']={'session_id':session['id'],'sha256':sha(result),'payload':payload,
                               'candidate_sha256':sha(result.get('candidate'))}
            task.update(cold_review='INTERPRETED',next_role='Evaluator')
            cycle['phase']='COLD_INTERPRETED'
        else:
            cycle.setdefault('cold_reviews',[]).append({'raw':cycle['cold_raw'],'interpreted_session':session['id'],'sha256':sha(result),'candidate_sha256':sha(result.get('candidate'))})
            cycle['cold_due']=False;task.pop('cold_review');task['next_role']='PI';cycle['phase']='FRESH_PI'
        return True
    elif role=='Evaluator' and task.get('research_job'):
        job=state['jobs'][task['research_job']]
        valid=job.get('status')=='SUCCEEDED' and payload['verdict'] not in {'INVALID'} and not payload['missing_evidence']
        outcome={'job_id':task.pop('research_job'),'evaluation_session':session['id'],'valid':valid,'verdict':payload['verdict'], 'sha256':sha(result)}
        cycle['experiments'].append(outcome)
        if valid:
            cycle['valid_cycles']+=1
            root=state['research'][task.get('package_id',task['stage_id'])]
            root['valid_cycles']=root.get('valid_cycles',0)+1
            for hypothesis in cycle['hypotheses']:
                # Dispositions must be explicit in the independent evaluation.
                choices=[x for x in payload['evidence_coverage'] if x.startswith(hypothesis['id']+':')]
                status=choices[0].split(':',1)[1] if len(choices)==1 else 'INCONCLUSIVE'
                hypothesis['status']=status if status in {'SUPPORTED','FALSIFIED','INCONCLUSIVE'} else 'INCONCLUSIVE'
            if root['valid_cycles']%3==0:cycle['cold_due']=True
            if payload['verdict']=='PASS' and payload.get('conclusion_layer')=='CPU':
                for condition in task.get('criteria',[]):
                    bindings=[e for e in state['evidence'].values() if e.get('job_id')==job['id'] and e.get('independent_verifier')==session['id'] and condition['id'] in e.get('verified_conditions',[e.get('verified_condition')])]
                    if condition['layer']=='cpu' and condition['id'] in payload['evidence_coverage'] and bindings:
                        cycle.setdefault('completion_evidence',{})[condition['id']]={'session_id':session['id'],'evidence_id':bindings[0]['id'],'candidate':result['candidate']}
        if payload['verdict']!='PASS':
            cycle['negative_results'].append(outcome)
            cycle.setdefault('counterevidence',[]).append({**outcome,'findings':payload.get('findings',[]),'missing_evidence':payload['missing_evidence']})
        task['next_role']='PI';cycle['phase']='FRESH_PI';return True
    elif role=='Scout':
        if not 1<=len(payload['cards'])<=3:raise Conflict('Scout needs 1..3 candidates')
        task['next_role']='PI';cycle['phase']='FRESH_PI';return True
    return False


def requests(state, task, session, result):
    allowed = {
        'PI': {'REQUEST_COMPLETE','REQUEST_DECOMPOSITION','REQUEST_EVIDENCE_DETAIL','REQUEST_REVIEW','REQUEST_REWORK','REQUEST_EXPERIMENT','REQUEST_PROPOSAL','REQUEST_CONTRACT_DECISION','REQUEST_MODEL_ESCALATION'},
        'Engineer': {'REQUEST_EVIDENCE_DETAIL','REQUEST_REVIEW','REQUEST_CONTRACT_DECISION','REQUEST_MODEL_ESCALATION'},
        'Evaluator': {'REQUEST_EVIDENCE_DETAIL','REQUEST_REWORK','REQUEST_CONTRACT_DECISION','REQUEST_MODEL_ESCALATION'},
        'Critic': {'REQUEST_EVIDENCE_DETAIL','REQUEST_REVIEW','REQUEST_PROPOSAL','REQUEST_CONTRACT_DECISION','REQUEST_MODEL_ESCALATION'},
        'Designer': {'REQUEST_EVIDENCE_DETAIL','REQUEST_EXPERIMENT','REQUEST_CONTRACT_DECISION','REQUEST_MODEL_ESCALATION'},
        'Scout': {'REQUEST_EVIDENCE_DETAIL','REQUEST_PROPOSAL','REQUEST_CONTRACT_DECISION','REQUEST_MODEL_ESCALATION'}}
    actions=result['requested_actions']
    decompositions=[a for a in actions if a['action']=='REQUEST_DECOMPOSITION']
    if decompositions and (len(actions)!=1 or result['payload'].get('proposal_required') or result['payload'].get('decision')=='STOP'):
        raise Conflict('decomposition must be the sole in-scope continuation action')
    for a in actions:
        if a['action'] not in allowed[session['role']] or not a['purpose'].strip():
            raise Conflict('role action not authorized or purpose missing')
        if a['action']=='REQUEST_COMPLETE':
            if len(actions)!=1 or a['fields'] or not completion_ready(state,task):
                raise Conflict('completion requires current independent proof of every approved condition and completed cold review')
            cycle=record(state,task);task['condition_evidence']={c['id']:cycle['completion_evidence'][c['id']]['evidence_id'] for c in task['criteria']}
            task.update(status='DONE');task['completion']['cpu']=True;cycle['phase']='COMPLETE'
            state['packages'][task['package_id']]['achievements'][task['id']]=dict(task['condition_evidence'])
            state['autonomous_tasks']=[tid for tid in state.get('autonomous_tasks',[]) if tid!=task['id']]
        elif a['action']=='REQUEST_DECOMPOSITION':
            from .decomposition import apply
            apply(state,task,session,a)
        elif a['action']=='REQUEST_REVIEW' and a['fields']==['Scout']:
            cycle=record(state,task);index=cycle['valid_cycles']
            if index in cycle['scout_cycles']:raise Conflict('Scout consultation quota exhausted')
            cycle['scout_cycles'].append(index)
            task.update(next_role='Scout',consultation_id='C-'+task['cycle_id'])
        elif a['action']=='REQUEST_REVIEW':
            if len(a['fields'])!=1 or a['fields'][0] not in {'Critic','Designer','Evaluator'}:
                raise Conflict('review request requires one supported independent role')
            if task['status'] not in {'DONE','CONTRACT_DECISION'}:task['next_role']=a['fields'][0]
        elif a['action']=='REQUEST_EXPERIMENT':
            if len(a['fields'])!=1:raise Conflict('experiment request requires one exact specification identity')
            for job in state['jobs'].values():
                if job.get('stage')==task['stage_id'] and job.get('spec',{}).get('id')==a['fields'][0]:
                    owner=state.get('evidence',{}).get('E-'+job['id'],{}).get('task_id')
                    if owner and owner!=task['id']:raise Conflict('experiment already belongs to another task')
            used=[state['jobs'].get(e['job_id'],{}).get('spec',{}).get('id') for e in record(state,task)['experiments']]
            if a['fields'][0] in used:raise Conflict('experiment already evaluated; select a new approved discriminator or conclude')
            if task['status'] not in {'DONE','CONTRACT_DECISION'}:
                task.update(status='WAITING_EXPERIMENT',experiment_request=a['fields'][0])
        elif a['action']=='REQUEST_CONTRACT_DECISION':
            task.update(status='CONTRACT_DECISION',last_error=a['purpose'])
        elif a['action']=='REQUEST_PROPOSAL':
            task['proposal_request']=a
        elif a['action']=='REQUEST_REWORK' and task['status'] not in {'DONE','CONTRACT_DECISION'}:
            task['next_role']='Engineer'


def completion_ready(state,task):
    """Fresh PI may close only independently proved, still-current conditions."""
    if not task.get('research_mode') or not task.get('package_id'):return False
    cycle=record(state,task)
    if cycle.get('cold_due') or task.get('cold_review'):return False
    proof=cycle.get('completion_evidence',{})
    if any(c['id'] not in proof for c in task['criteria']):return False
    from .engine import envelope_candidate
    for c in task['criteria']:
        item=proof[c['id']];se=state['sessions'].get(item['session_id'],{})
        if c['layer']!='cpu' or se.get('status')!='ACCEPTED' or se.get('role')!='Evaluator' or se.get('task_id')!=task['id']:
            return False
        if item['candidate']!=envelope_candidate(task):return False
    return True
