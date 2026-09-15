"""Bounded working context with lossless, hash-bound read-only history."""
from copy import deepcopy
from .store import atomic,canonical,sha


def project(task,research,decisions,evidence):
    decisions=sorted(decisions,key=lambda d:(d.get('event_sequence',0),d.get('id','')))
    evidence=sorted(evidence,key=lambda e:(e.get('event_sequence',0),e.get('id','')))
    history={'task':task,'research':research,'decisions':decisions,'evidence':evidence}
    digest=sha(history)
    t={k:deepcopy(v) for k,v in task.items() if k not in {'results','requested_actions','evidence_details','diagnostic','proposal_request','interpretation'}}
    r=deepcopy(research)
    for key,limit in [('experiments',5),('hypothesis_history',3),('negative_results',3),('counterevidence',3),('cold_reviews',1),('scout_cycles',3)]:
        if isinstance(r.get(key),list):r[key]=r[key][-limit:]
    # Current findings, active hypotheses and frozen conditions remain intact.
    needed=set(task.get('condition_evidence',{}).values())
    needed.update(e for f in task.get('findings',[]) for e in f.get('evidence_refs',[]))
    selected=evidence[-12:]
    selected_ids={e['id'] for e in selected}
    selected=[e for e in evidence if e['id'] in needed and e['id'] not in selected_ids]+selected
    return t,r,decisions[-5:],selected,history,{'sha256':digest,'roles':len(task.get('results',[])),
        'decisions':len(decisions),'evidence':len(evidence),'experiments':len(research.get('experiments',[])),
        'counterevidence':len(research.get('counterevidence',[]))}


def save(directory,history):
    from pathlib import Path
    path=Path(directory)/'evidence'/'context-history.json'
    atomic(path,canonical({'sha256':sha(history),'history':history}))
    return str(path)
