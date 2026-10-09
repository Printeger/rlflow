"""Optional snapshot construction outside the business writer transaction.

This compatibility full-state builder is bounded by input bytes/time, not a
streaming chunk snapshot. Failure leaves due pending and older snapshots intact.
"""
import hashlib
import json
import math
import sqlite3
import threading
import time
from .store import canonical, Conflict


def maintain(store,*,seconds=5,max_bytes=32*1024*1024,max_rows=100000,max_nodes=2000000):
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0 or any(type(v) is not int or v<1 for v in (max_bytes,max_rows,max_nodes)):
        raise ValueError('invalid snapshot maintenance bounds')
    deadline=time.monotonic()+seconds
    def check():
        if time.monotonic()>deadline:raise TimeoutError('snapshot maintenance deadline')
    try:
        with store.lock('snapshot-maintenance',nonblocking=True):
            with sqlite3.connect(store.db.as_uri()+'?mode=ro',uri=True,timeout=0) as db:
                db.row_factory=sqlite3.Row;db.execute('BEGIN')
                db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
                due=db.execute('SELECT * FROM snapshot_due WHERE singleton=1').fetchone()
                if due is None or not due['due_version']:return False
                version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
                if version<due['due_version']:return False
                tip=db.execute('SELECT event_id,payload_sha256,new_state_version FROM events WHERE seq=?',(version,)).fetchone()
                if tip is None or tip['new_state_version']!=version:return False
                registration=store._goal_registration(db)
                budget=[max_bytes]
                nodes=[max_nodes]
                def parse(raw):
                    # Conservative preflight BEFORE allocating the JSON tree.
                    # Delimiters inside strings may overcount; skipping optional
                    # maintenance is safe, silently relaxing limits is not.
                    nodes[0]-=1+sum(raw.count(c) for c in (b'{',b'[',b',',b':'))
                    if nodes[0]<0:raise ValueError('snapshot structural budget exceeded')
                    check();return json.loads(raw)
                def decode(value):
                    check()
                    if isinstance(value,dict) and set(value) in ({'$rlflow_blob'},{'$rlflow_blob','literal'}):
                        row=db.execute('SELECT data FROM blobs WHERE digest=? AND length(data)<=?',(value['$rlflow_blob'],budget[0])).fetchone()
                        if row is None:raise Conflict('snapshot blob unavailable or exceeds budget')
                        budget[0]-=len(row[0])
                        if hashlib.sha256(row[0]).hexdigest()!=value['$rlflow_blob']:raise Conflict('snapshot blob integrity mismatch')
                        literal=value.get('literal',False);value=parse(row[0])
                        if literal:return value
                    if isinstance(value,dict):return {k:decode(v) for k,v in value.items()}
                    if isinstance(value,list):return [decode(v) for v in value]
                    return value
                state={'version':version};count=0
                # Bound each raw descriptor before SQLite returns it to Python.
                size='length(CAST(section AS BLOB))+length(CAST(object_key AS BLOB))+length(CAST(value AS BLOB))'
                query=f'SELECT CASE WHEN {size}<=? THEN section END AS section,CASE WHEN {size}<=? THEN object_key END AS object_key,CASE WHEN {size}<=? THEN value END AS value FROM projection ORDER BY section,object_key'
                for row in db.execute(query,(max_bytes,max_bytes,max_bytes)):
                    check();count+=1
                    if count>max_rows or row['value'] is None:raise ValueError('snapshot projection exceeds bound')
                    raw=row['value'].encode();budget[0]-=len(raw)+len(row['section'].encode())+len(row['object_key'].encode())
                    if budget[0]<0:raise ValueError('snapshot bytes exceed bound')
                    value=decode(parse(raw))
                    if row['object_key']=='':state[row['section']]=value
                    else:state.setdefault(row['section'],{})[row['object_key']]=value
                # Resolve only the command keys in this consistent snapshot;
                # the UNIQUE idempotency-key index avoids any history scan.
                source_events={key:store._goal_event(db,key) for key in state.get('hybrid_goal_commands',{})}
                def source_parse(raw):
                    budget[0]-=len(raw)
                    if budget[0]<0:raise ValueError('snapshot source witness exceeds byte budget')
                    return parse(raw)
                goal_sources={key:store._goal_source(db,key,max_bytes=max(0,min(budget[0],16*1024*1024)),_parse=source_parse,_decode=decode)
                              for key in state.get('hybrid_goal_commands',{})}
                authority_events={key:store._authority_event(db,key,max_bytes=max(0,min(budget[0],3*1024*1024)),_parse=source_parse,_decode=decode)
                                  for key in state.get('hybrid_approval_commands',{})}
                preparation_events={key:store._preparation_event(db,key,max_bytes=max(0,min(budget[0],4*1024**2)),_parse=source_parse,_decode=decode)
                                    for section in ('hybrid_preparation_intents','hybrid_preparation_results')
                                    for key in state.get(section,{})}
                controller_events={key:store._controller_event(db,key,max_bytes=max(0,min(budget[0],256*1024)),_parse=source_parse,_decode=decode)
                                   for key in state.get('hybrid_controller_facts',{})}
                controller_tip=store._controller_tip(db,version)
                admission_events={key:store._admission_event(db,key,max_bytes=max(0,min(budget[0],256*1024)),_parse=source_parse,_decode=decode)
                                  for key in state.get('hybrid_admission_facts',{})}
                admission_summary=store._admission_summary(db,version)
                budget_events={key:store._budget_event(db,key,max_bytes=max(0,min(budget[0],1024*1024)),_parse=source_parse,_decode=decode)
                               for key in state.get('hybrid_budget_entries',{})}
                budget_summary=store._budget_summary(db,version)
                workspace_events={key:store._workspace_event(db,key,max_bytes=max(0,min(budget[0],1024*1024)),_parse=source_parse,_decode=decode)
                                  for key in state.get('hybrid_workspace_facts',{})}
                workspace_summary=store._workspace_summary(db,version)
            check()
            from .contracts import validate_runtime_state
            validate_runtime_state(state);check()
            from .hybrid_goals import validate_complete
            validate_complete(state,registration,source_events.get,goal_sources.get);check()
            from .hybrid_authority import validate_complete as authority_complete
            authority_complete(state,registration,authority_events.get);check()
            from .hybrid_preparation import validate_complete as preparation_complete
            preparation_complete(state,registration,preparation_events.get);check()
            from .hybrid_controller import validate_complete as controller_complete
            controller_complete(state,registration,controller_events.get,event_tip=controller_tip);check()
            from .hybrid_admission import validate_complete as admission_complete
            admission_complete(state,registration,admission_events.get,event_summary=admission_summary);check()
            from .hybrid_budget_ledger import validate_complete as budget_complete
            budget_complete(state,registration,budget_events.get,event_summary=budget_summary);check()
            from .hybrid_workspace import validate_complete as workspace_complete
            workspace_complete(state,registration,workspace_events.get,event_summary=workspace_summary);check()
            raw=canonical(state);check()
            if len(raw)>max_bytes:return False
            digest=hashlib.sha256(raw).hexdigest();check()
            with store.lock(nonblocking=True),sqlite3.connect(store.db,timeout=0) as db:
                db.execute('BEGIN IMMEDIATE')
                if store._goal_registration(db)!=registration:return False
                current=db.execute('SELECT event_id,payload_sha256,new_state_version FROM events WHERE seq=?',(version,)).fetchone()
                head=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()
                if current!=tuple(tip) or head is None or head[0]<version:return False
                metadata=db.execute('SELECT due_version,last_complete FROM snapshot_due WHERE singleton=1').fetchone()
                if (metadata is None or any(type(v) is not int or not 0<=v<=head[0] for v in metadata)
                        or metadata[1] and not db.execute('SELECT 1 FROM snapshots WHERE version=?',(metadata[1],)).fetchone()):return False
                existing=db.execute("SELECT sha256,CASE WHEN typeof(state)='blob' AND length(CAST(state AS BLOB))<=? THEN state END FROM snapshots WHERE version=?",(max_bytes,version)).fetchone()
                if existing and (existing[0]!=digest or existing[1] is None or hashlib.sha256(existing[1]).hexdigest()!=digest):return False
                db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',(version,raw,digest))
                if db.execute('UPDATE snapshot_due SET due_version=CASE WHEN due_version<=? THEN 0 ELSE due_version END,last_complete=MAX(last_complete,?) WHERE singleton=1',(version,version)).rowcount!=1:
                    raise Conflict('snapshot maintenance acknowledgement missing')
            return True
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,RecursionError,OverflowError):return False


class Maintenance:
    """One optional job, no second scheduler; daemon loop remains responsive."""
    def __init__(self,store):self.store,self.thread,self.last=store,None,-math.inf
    def tick(self):
        now=time.monotonic()
        if now-self.last<60 or self.thread is not None and self.thread.is_alive():return False
        self.last=now
        self.thread=threading.Thread(target=maintain,args=(self.store,),daemon=True,name='snapshot-maintenance')
        self.thread.start();return True
