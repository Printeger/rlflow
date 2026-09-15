"""Bounded, provenance-preserving evidence requests; no arbitrary file access."""
import json
from pathlib import Path
from .store import Conflict, canonical, sha, atomic

FIELDS = {'payload', 'evidence_refs', 'candidate', 'observations', 'counterevidence', 'summary', 'missing_evidence', 'sources', 'status', 'exit_code', 'spec_sha256'}


def detail(store, session_id, request):
    s = store.replay();se = s['sessions'][session_id];task=s['tasks'][se['task_id']]
    if se['status'] != 'ACCEPTED' or task['version'] != se['task_version']+1:
        raise Conflict('stale evidence request')
    if not request['purpose'].strip() or not request['fields'] or not set(request['fields']) <= FIELDS:
        raise Conflict('unsupported evidence fields or missing purpose')
    result = []
    for eid in request['evidence_ids']:
        e=s['evidence'].get(eid)
        if not e or not e.get('accepted') or eid not in reachable(s,task):
            raise Conflict('evidence outside task/package authority')
        path,value=read_source(store,e)
        selected={field:value.get(field, value.get('payload',{}).get(field)) for field in sorted(set(request['fields']))}
        result.append({'id':eid,'source':str(path),'sha256':e['sha256'],'fields':selected})
    if len(canonical(result))>64000: raise Conflict('evidence request exceeds 64k byte bound')
    digest=sha({'session':session_id,'ids':sorted(request['evidence_ids']),'fields':sorted(set(request['fields']))})
    path=store.root/'evidence_details'/(digest+'.json')
    atomic(path,canonical(result))
    def change(state):
        t=state['tasks'][task['id']]
        t.setdefault('evidence_details',{})[digest]={'path':str(path),'sha256':sha(result),'objects':result}
    store.transact('EVIDENCE_DETAIL_SERVED','detail:'+digest,change,object_id=session_id,expected=s['version'])
    return result


def materialize(store, state, task, directory):
    """Copy only accepted, task-related source objects into a read-only role mount."""
    rows=[]
    for eid,e in sorted(reachable(state,task).items()):
        if not e.get('accepted') or not e.get('path'):continue
        if not task.get('package_id') and e.get('task_id')!=task['id']:continue
        # Raw cold review excludes PI/critic interpretations.
        if task.get('cold_review')=='RAW' and e.get('role') in {'PI','Critic','Designer','Scout'}:continue
        path,value=read_source(store,e)
        name=sha({'id':eid})+'.json';target=Path(directory)/'evidence'/name
        atomic(target,canonical({'id':eid,'source':str(path),'sha256':e['sha256'],'object':value}))
        rows.append({'id':eid,'read_only_path':str(target),'sha256':e['sha256']})
    return rows


def reachable(state,task):
    """Legacy evidence visibility is retained; packages get only bound objects."""
    if not task.get('package_id'):return state['evidence']
    package=state['packages'][task['package_id']]
    inputs={c['evidence_id']:c['sha256'] for exp in package['spec'].get('experiments',[]) for c in exp['conditions']}
    return {eid:e for eid,e in state['evidence'].items() if e.get('task_id')==task['id']
            or e.get('package_id')==task['package_id'] or inputs.get(eid)==e.get('sha256') and eid in inputs}


def read_source(store,e):
    source=Path(e['path'])
    path=source/('receipt.json' if e.get('job_id') else 'result.json')
    roots=[store.root/name for name in ('roles','jobs','literature')]
    if path.is_symlink() or not any(path.resolve().is_relative_to(root) for root in roots):
        raise Conflict('evidence source escapes trusted storage')
    if not path.is_file() or path.stat().st_size>1024*1024:
        raise Conflict('invalid bounded evidence source')
    value=json.loads(path.read_text())
    if sha(value)!=e['sha256']:raise Conflict('evidence hash mismatch')
    return path,value


def recovery_material(store,state,task,directory):
    """Preserve partial work and completed command records for a fresh role."""
    sid=task.get('recovery_source')
    if not sid:return None
    se=state['sessions'][sid];source=Path(se['directory'])
    if source.is_symlink() or not source.resolve().is_relative_to(store.root/'roles'):raise Conflict('recovery source outside trusted storage')
    commands=[]
    for path in sorted((source/'commands').glob('*/intent.json')):
        row={'id':path.parent.name,'intent':json.loads(path.read_text()),'status':'UNKNOWN'}
        result=path.parent/'result.json'
        if result.exists():
            row.update(status='COMPLETED',result=json.loads(result.read_text()))
        commands.append(row)
    value={'session_id':sid,'accepted':False,'reason':se.get('error'),'commands':commands,
           'instruction':'Preserve completed work and inspect original command outcomes. Unknown commands must not be repeated. This is recovery context, not independent acceptance evidence.'}
    if len(canonical(value))>1024*1024:raise Conflict('recovery command material too large; bounded review required')
    target=Path(directory)/'evidence'/'recovery.json';atomic(target,canonical(value))
    return {'recovery_source':sid,'read_only_path':str(target),'sha256':sha(value)}
