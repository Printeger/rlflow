"""Evidence-bound, single-use compute escalation. Never grants new authority."""
import hashlib
import json
from pathlib import Path
from .store import Conflict, canonical, sha, atomic
from .model_policy import load_policy, select
from .policy import candidate, require_stage, stopped
from .role_config import load_role

REASONS = {
 'E01_CONTRADICTORY_EVIDENCE': {'PI','Critic','Designer','Evaluator'},
 'E02_ARCHITECTURE_DECISION': {'PI','Engineer','Designer'},
 'E03_HIGH_COST_EXPERIMENT': {'Designer','PI'},
 'E04_HIGH_RISK_ACCEPTANCE': {'Evaluator'},
 'E05_CROSS_MODULE_ROOT_CAUSE': {'Engineer','Critic'},
 'E06_SOL_HIGH_INCONCLUSIVE': {'PI','Engineer','Critic','Designer','Evaluator'},
 'E07_SOURCE_AMBIGUITY': {'Scout'},
}


def authority(stage, role):
    return sha({k:stage[k] for k in ('repo','scope','module_roots','protected_paths','categories','cpu_only')} | {'role':role})


def evidence_files(store, state, task, ids):
    if not isinstance(ids,list) or not 1 <= len(ids) <= 8 or any(not isinstance(x,str) for x in ids) or len(set(ids)) != len(ids):
        raise Conflict('escalation requires 1..8 distinct accepted evidence IDs')
    files=[]
    for eid in ids:
        e=state['evidence'].get(eid)
        if not e or not e.get('accepted'):
            raise Conflict('unaccepted escalation evidence')
        source=state['sessions'].get(eid.removeprefix('E-'))
        if not source or source['task_id'] != task['id'] or source['status'] != 'ACCEPTED':
            raise Conflict('evidence must come from this task and an accepted session')
        directory=Path(e['path'])
        if directory.resolve() != Path(source['directory']).resolve() or not directory.resolve().is_relative_to(store.root/'roles'):
            raise Conflict('evidence directory outside trusted role storage')
        result=directory/'result.json'
        if result.is_symlink() or sha(json.loads(result.read_text())) != e['sha256']:
            raise Conflict('accepted evidence changed')
        refs=[(result,hashlib.sha256(result.read_bytes()).hexdigest())]
        validation=json.loads((directory/'validation.json').read_text())
        refs += [(Path(x['path']), x['sha256']) for x in validation.get('self_test_artifacts',[])]
        audit=validation.get('command_audit')
        if audit: refs.append((Path(audit['path']),audit['sha256']))
        for path,digest in refs:
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
                raise Conflict('evidence file outside assigned session')
            if path.stat().st_size > 1_000_000 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise Conflict('evidence file changed or too large')
            files.append({'evidence_id':eid,'source':str(path),'sha256':digest})
    if sum(Path(f['source']).stat().st_size for f in files)>2_000_000:
        raise Conflict('escalation evidence exceeds bounded package')
    return files


def register_case(store, spec):
    required={'id','task_id','source_session','reason_code','evidence_refs','question','expected_output','competing_explanations'}
    if set(spec)!=required or any(not isinstance(spec[k],str) or not spec[k].strip() or len(spec[k])>4000
                                for k in required-{'evidence_refs','competing_explanations'}):
        raise Conflict('invalid escalation case fields')
    if not isinstance(spec['competing_explanations'],list) or not 1<=len(spec['competing_explanations'])<=3 or any(not isinstance(x,str) or not x.strip() or len(x)>2000 for x in spec['competing_explanations']):
        raise Conflict('need 1..3 competing explanations')
    state=store.replay();task=state['tasks'][spec['task_id']];source=state['sessions'][spec['source_session']]
    existing=state['decisions'].get(spec['id'])
    if existing:
        if all(existing.get(k)==v for k,v in spec.items()):return existing
        raise Conflict('case ID already bound to different content')
    if source['task_id']!=task['id'] or source['status']!='ACCEPTED' or 'compute' not in source:
        raise Conflict('escalation needs a valid completed model session, never an infrastructure failure')
    role=source['role'];reason=spec['reason_code']
    if role not in REASONS.get(reason,set()):raise Conflict('reason not permitted for role')
    if reason=='E01_CONTRADICTORY_EVIDENCE' and (len(spec['evidence_refs'])<2 or len(spec['competing_explanations'])<2):
        raise Conflict('contradiction needs distinct evidence and competing explanations')
    stage=require_stage(state,task['stage_id'])
    if any(x['task_id']==task['id'] and x['status'] in {'START_INTENT','RUNNING','RECONCILE'} for x in state['sessions'].values()):
        raise Conflict('cannot authorize a case while task is running')
    p=load_policy();steps=p['roles'][role];step=source['compute']['step']
    if step>=len(steps)-1 or steps[step]!={k:source['compute'][k] for k in ('model','effort')}:
        raise Conflict('source profile has no next policy step')
    if steps[step+1]['model']=='gpt-6-astra' and reason=='E06_SOL_HIGH_INCONCLUSIVE':
        raise Conflict('inconclusive alone cannot authorize Astra; specify substantive high-value reason')
    from .engine import envelope_candidate
    source_result=json.loads((Path(source['directory'])/'result.json').read_text())
    evidence_files(store,state,task,['E-'+source['id']])
    if candidate(task['repo']) != task.get('accepted_candidate',task['baseline']) or source_result.get('candidate')!=envelope_candidate(task):
        raise Conflict('source candidate is stale')
    files=evidence_files(store,state,task,spec['evidence_refs'])
    case={**spec,'kind':'model_escalation_case','role':role,'from_step':step,'to_step':step+1,
          'candidate':candidate(task['repo']),'authority_sha256':authority(stage,role),
          'role_sha256':load_role(role)['sha256'],'policy_sha256':p['sha256'],'files':files,
          'authorized_by':'local-user-cli','consumed_by':None}
    def save(s):
        if spec['id'] in s['decisions']:raise Conflict('case ID already exists')
        s['decisions'][spec['id']]=case
        return case
    store.transact('MODEL_CASE_AUTHORIZED','model-case:'+spec['id'],save,expected=state['version'],object_id=spec['id'],producer='user-cli')
    return case


def validate_case(store,state,case_id,source_id=None):
    c=state['decisions'].get(case_id,{})
    if c.get('kind')!='model_escalation_case' or c.get('authorized_by')!='local-user-cli' or c.get('consumed_by'):
        raise Conflict('case is missing, unauthorized or already consumed')
    task=state['tasks'][c['task_id']];stage=require_stage(state,task['stage_id'])
    source=state['sessions'][source_id or c['source_session']]
    if (source['status']!='ACCEPTED' or source['task_id']!=task['id'] or source['role']!=c['role']
            or source.get('compute',{}).get('step')!=c['from_step']):
        raise Conflict('escalation source mismatch')
    p=load_policy()
    if c['policy_sha256']!=p['sha256'] or c['role_sha256']!=load_role(c['role'])['sha256']:
        raise Conflict('case policy/role definition changed; new authorization required')
    if candidate(task['repo'])!=c['candidate'] or authority(stage,c['role'])!=c['authority_sha256']:
        raise Conflict('candidate or authority changed since case authorization')
    from .engine import envelope_candidate
    evidence_files(store,state,task,['E-'+source['id']])
    result=json.loads((Path(source['directory'])/'result.json').read_text())
    if result.get('candidate')!=envelope_candidate(task):raise Conflict('source result candidate drift')
    current=evidence_files(store,state,task,c['evidence_refs'])
    if current!=c['files']:raise Conflict('case evidence changed')
    choice=select(stage,c['role'],p,c['to_step'])
    return c,choice,source


def queue(store,case_id,*,source_id=None):
    state=store.replay()
    # A replayed operator request is inert, even after a later session finishes.
    case=state['decisions'].get(case_id,{})
    if case.get('queued'):
        return state['tasks'][case['task_id']]
    c,choice,source=validate_case(store,state,case_id,source_id)
    task=state['tasks'][c['task_id']]
    if stopped(store.root) or task['status'] in {'RUNNING','DONE','STOPPED','RECONCILE'}:
        raise Conflict('task is not at an escalation boundary')
    package={'case_id':case_id,'source_session':source['id'],'question':c['question'],
             'expected_output':c['expected_output'],'reason_code':c['reason_code'],
             'competing_explanations':c['competing_explanations'],
             'current_conclusion':json.loads((Path(source['directory'])/'result.json').read_text())['payload'],
             'candidate':c['candidate'],'files':c['files'],'choice':choice}
    def enqueue(s):
        t=s['tasks'][task['id']]
        t.update(status='QUEUED',next_role=c['role'],version=t['version']+1,pending_escalation=package)
        t.pop('last_failure',None);t.pop('last_error',None)
        s['decisions'][case_id]['queued']=True
        return package
    store.transact('MODEL_ESCALATION_QUEUED','model-queue:'+case_id,enqueue,expected=state['version'],object_id=task['id'])
    return store.replay()['tasks'][task['id']]


def materialize(directory,package):
    target=Path(directory)/'evidence';target.mkdir()
    refs=[]
    for i,entry in enumerate(package['files']):
        raw=Path(entry['source']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise Conflict('evidence changed before dispatch')
        path=target/f'{i:02d}-{Path(entry["source"]).name}'
        atomic(path,raw)
        refs.append({'evidence_id':entry['evidence_id'],'path':str(path),'sha256':entry['sha256']})
    return {k:v for k,v in package.items() if k!='files'} | {'evidence_files':refs}
