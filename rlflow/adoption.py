"""Two distinct research adoption approvals; no implicit mainline writes."""
from .store import Conflict,sha,atomic,canonical


def matching_cold(root,digest):
    return any(review.get('candidate_sha256')==digest and review.get('raw',{}).get('candidate_sha256')==digest
               for cycle in root.get('cycles',{}).values() for review in cycle.get('cold_reviews',[]))


def propose(store,spec):
    fields={'stage_id','scope','mechanism_id','replacement','change','candidate_sha256','evidence_ids','counterevidence','stop_conditions'}
    if not isinstance(spec,dict) or set(spec)!=fields or spec['scope'] not in {'SANDBOX_ONLY','MAINLINE_ADOPTION'}:
        raise Conflict('complete sandbox/adoption proposal required')
    if not spec['replacement'].strip() or not spec['change'].strip() or not spec['stop_conditions'] or not spec['evidence_ids']:
        raise Conflict('replacement, evidence, exact change and stop conditions required')
    content={**spec,'budget':{'role_calls':0,'wall_seconds':0,'fake_starts':0},'preconditions':['independent evidence','single sandbox','separate mainline approval']}
    snapshot=store.replay().get('research',{}).get(spec['stage_id'],{})
    content['adoption_context']={'architecture':sha(snapshot.get('architecture')), 'sandbox':sha(snapshot.get('sandbox'))}
    digest=sha(content);pid='P-'+digest[:16]
    def change(s):
        for eid in spec['evidence_ids']:
            if not s['evidence'].get(eid,{}).get('accepted'):raise Conflict('adoption evidence not accepted')
        root=s.get('research',{}).get(spec['stage_id'],{})
        architecture=root.get('architecture',{})
        if spec['scope']=='SANDBOX_ONLY' and root.get('valid_cycles',0)<architecture.get('hold_until_valid_cycle',0):
            if not any(s['evidence'][eid].get('material_observation') and s['evidence'][eid].get('independent_verifier') for eid in spec['evidence_ids']):
                raise Conflict('architecture hold window requires independent material counterevidence')
        if spec['scope']=='MAINLINE_ADOPTION':
            sandbox=root.get('sandbox')
            if not sandbox or sandbox['mechanism_id']!=spec['mechanism_id'] or sandbox['candidate_sha256']!=spec['candidate_sha256']:
                raise Conflict('mainline adoption requires separately approved matching sandbox')
            if not matching_cold(root,spec['candidate_sha256']):raise Conflict('matching candidate Cold Review required before mainline adoption')
        for old in s['proposals'].values():
            c=old['content']
            same=c.get('candidate_sha256')==spec['candidate_sha256'] and c.get('scope')==spec['scope']
            rejected=any(a['proposal_id']==old['id'] and a['decision']=='REJECTED' for a in s['approvals'].values())
            if same and rejected and not set(spec['evidence_ids'])-set(c.get('evidence_ids',[])):
                raise Conflict('rejected mechanism cannot be renamed without new evidence')
        s['proposals'][pid]={'id':pid,'version':1,'content':content,'sha256':digest,'shown':False}
    store.transact('PROPOSAL_CREATED','proposal:'+digest,change,object_id=pid)
    atomic(store.root/'proposals'/(pid+'.json'),canonical(content));return pid


def approve_in(state,content,aid):
    root=state.setdefault('research',{}).setdefault(content['stage_id'],{})
    if content.get('adoption_context')!={'architecture':sha(root.get('architecture')), 'sandbox':sha(root.get('sandbox'))}:
        raise Conflict('adoption proposal context changed; refresh exact proposal')
    if content['scope']=='SANDBOX_ONLY':
        if root.get('sandbox'):raise Conflict('only one mechanism sandbox may be active')
        root['sandbox']={'approval_id':aid,'mechanism_id':content['mechanism_id'],'candidate_sha256':content['candidate_sha256']}
    else:
        sandbox=root.get('sandbox')
        if not sandbox or sandbox['mechanism_id']!=content['mechanism_id'] or sandbox['candidate_sha256']!=content['candidate_sha256']:
            raise Conflict('sandbox approval changed')
        if not matching_cold(root,content['candidate_sha256']):raise Conflict('missing matching staged Cold Review')
        root['architecture']={'approval_id':aid,'mechanism_id':content['mechanism_id'],'hold_until_valid_cycle':root.get('valid_cycles',0)+3}
        root.pop('sandbox')
    # This is a research approval object. It neither changes a task's permitted
    # modules nor runs git/merges; actual implementation needs the exact package.
