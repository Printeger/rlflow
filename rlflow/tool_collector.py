"""Trusted private tool ledger: bounded discovery and transactional recovery.

Does not grant authority, execute commands, or publish raw artifacts. Completion
and verification are distinct. Public tool projection is a separate integration.
"""
from __future__ import annotations
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from . import tool_journal as journal
from .startup_observation import collect as startup_collect
from .store import Conflict, sha

BINDINGS = ('generation','release_binding','identity','directory','scratch','before','limit','resources','role','task_id','stage_id','launch_phase')
ACTIVE = {'START_INTENT','RUNNING','RECONCILE'}
INTENT_LIMIT = 16*1024*1024  # <=4MiB request permissions can expand 3x in ASCII JSON + 100k command.
RESULT_LIMIT = 6*1024*1024  # Command appears twice + bounded output tails, including JSON escaping.


class SourceCapacityError(ValueError):
    pass


def read_json(directory,name,limit=65536):
    fd = os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    with os.fdopen(fd,'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):raise ValueError('invalid tool fact storage')
        if info.st_size>limit:raise SourceCapacityError('tool fact exceeds supported capacity')
        raw = stream.read(limit+1)
        if len(raw)>limit:raise SourceCapacityError('tool fact exceeds supported capacity')
        value = json.loads(raw)
        if not isinstance(value,dict):raise ValueError('invalid tool fact')
        return value


def source_id(sid,generation):
    return sha({'session':sid,'generation':generation})


def semantic(row):
    return sha({k:row[k] for k in ('context','command_digest','intent_sha256','launch_witness')})


def _context(sid,session):
    release = session.get('release_binding') or {}
    value = {'schema_version':'1.0','session':sid,'generation':session.get('generation'),
             'request_sha256':release.get('request_sha256'),'candidate_sha256':sha(session.get('before'))}
    return value if journal.context_valid(value) else None


def _source(identity,context):
    return {'schema_version':'1.0','id':identity,'context':context,'cursor':None,'pending_after':'',
            'status':'ACTIVE','reason':None,'incomplete_tail':False,'revision':0}


def _receipt(identity,row):
    return {'schema_version':'1.0','id':identity+':'+row['command_digest'],'source_id':identity,'registration':row,
            'semantic_digest':semantic(row),'status':'PENDING','verification':'PENDING','reason':None,
            'fact':None,'validation_digest':None}


def _page(store,section,status,after,limit,prefix=''):
    # projection_status is (section, object_status, object_key): range keyset.
    query = 'SELECT object_key,value FROM projection WHERE section=? AND object_status=? AND object_key>?'
    args = [section,status,after]
    if prefix:query+=' AND object_key>=? AND object_key<?';args += [prefix,prefix+'g']
    query+=' ORDER BY object_key LIMIT ?';args.append(limit)
    with store.connect() as db:
        db.execute('BEGIN')
        rows = [(key,store._decode_value(db,json.loads(raw))) for key,raw in db.execute(query,args)]
    if not rows and after:
        return _page(store,section,status,'',limit,prefix)
    return rows


def _commit(store,sid,session,identity,before,source,old,updates):
    changed = {key:value for key,value in updates.items() if old.get(key)!=value}
    if before==source and not changed:return False
    source = dict(source,revision=before['revision']+1 if before else 1)
    key = 'tool_ingest:'+sha({'before':before,'source':source,'receipts':changed,'binding':{k:session.get(k) for k in BINDINGS}})
    def attach(state):
        current = state['sessions'].get(sid)
        if not current or any(current.get(k)!=session.get(k) for k in BINDINGS):raise Conflict('tool source generation changed')
        if state.get('tool_sources',{}).get(identity)!=before:raise Conflict('tool source checkpoint changed')
        for rid,value in changed.items():
            prior = state.get('tool_receipts',{}).get(rid)
            if prior!=old.get(rid):raise Conflict('tool receipt concurrently changed')
            if prior is not None and prior['semantic_digest']!=value['semantic_digest']:raise Conflict('tool receipt semantic conflict')
            state.setdefault('tool_receipts',{})[rid] = value
        state.setdefault('tool_sources',{})[identity] = source
        return {'source_id':identity,'registered':sum(old.get(rid) is None for rid in changed),
                'collected':sum(v['status']=='COLLECTED' for v in changed.values()),
                'verified':sum(v['verification']=='VERIFIED' for v in changed.values())}
    result = store.transact_objects('ROLE_TOOL_OBSERVED',key,[('sessions',sid),('tool_sources',identity),
                                    *(('tool_receipts',rid) for rid in changed)],attach,object_id=identity)
    if result['duplicate']:
        # _existing checks only event kind/entity. Verify actual semantic values too.
        for rid,value in changed.items():
            if store.get('tool_receipts',rid)!=value:raise Conflict('duplicate tool receipt content conflict')
    return not result['duplicate']


def _request(directory,store,sid,session,context):
    request = read_json(directory,'request.json',4*1024*1024)
    if (sha(request)!=context['request_sha256'] or request.get('id')!=sid or request.get('root')!=str(store.root)
            or request.get('directory')!=session['directory'] or request.get('generation')!=session['generation']
            or any(request.get(k)!=session.get(k) for k in ('scratch','before','limit','resources','role','task_id','stage_id'))):
        raise ValueError('tool request binding mismatch')
    return request


def _return(directory,path,request,session,context,row,launch):
    """At most one bounded intent/result at a time; no raw text leaves this call."""
    command = os.open('commands',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
    try:fd = os.open(row['command_digest'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=command)
    finally:os.close(command)
    with contextlib.ExitStack() as stack:
        stack.callback(os.close,fd)
        intent = read_json(fd,'intent.json',INTENT_LIMIT)
        if sha(intent)!=row['intent_sha256']:raise ValueError('registered intent changed')
        try:result = read_json(fd,'result.json',RESULT_LIMIT)
        except FileNotFoundError:return None
        from .isolation import IsolationError, tool_return_observation
        try:fact = tool_return_observation(intent,result)
        except IsolationError as error:raise ValueError('invalid tool return metadata') from error
        try:stored = read_json(fd,'return-observation.json')
        except FileNotFoundError:stored = fact  # Core recovers fixed proof, never reruns/rewrites raw source.
        if stored!=fact:raise ValueError('tool return fact changed')
    witness = row['launch_witness']
    if witness is None:return fact,'UNVERIFIED','REGISTER_UNVERIFIED',None
    runtime = request.get('cpu_runtime')
    read_extra = []
    try:evidence = os.stat('evidence',dir_fd=directory,follow_symlinks=False)
    except FileNotFoundError:evidence = None
    if evidence and stat.S_ISDIR(evidence.st_mode):read_extra.append(str(path/'evidence'))
    if runtime:read_extra.append(runtime['root'])
    permissions = {'write_roots':request.get('write_roots'),'read_extra':read_extra,
                   'execute_extra':[runtime['root']] if runtime else [],'command_seconds':request.get('command_seconds',120)}
    cid,timeout = intent.get('command_id'),intent.get('timeout')
    expected_path = path/'commands'/row['command_digest']
    valid = (set(intent)=={'command_id','command','timeout','candidate','role','permissions','tool_context','scratch','memory_bytes'}
             and intent.get('tool_context')==context and intent.get('permissions')==permissions and intent.get('role')==request['role']
             and intent.get('candidate')==str(Path(request['repo']).resolve(strict=True))
             and intent.get('scratch')==str(Path(request['scratch']).resolve(strict=True))
             and intent.get('memory_bytes')==(runtime['address_space_bytes'] if runtime else 2*1024**3)
             and isinstance(cid,str) and 0<len(cid)<=200 and isinstance(intent.get('command'),str)
             and type(timeout) in (int,float) and math.isfinite(timeout) and 1<=timeout<=permissions['command_seconds']
             and hashlib.sha256(json.dumps({'id':cid},sort_keys=True).encode()).hexdigest()==row['command_digest']
             and set(result)=={'infrastructure_error','command','argv','cwd','exit_code','timed_out','wall_seconds','stdout','stderr','checkpoint'}
             and result.get('command')==intent['command'] and result.get('argv')==['/bin/bash','--noprofile','--norc','-c',intent['command']]
             and result.get('cwd')==intent['scratch'] and result.get('checkpoint')==str(expected_path)
             and isinstance(result.get('stdout'),str) and isinstance(result.get('stderr'),str)
             and launch is not None and witness==launch)
    verification = 'VERIFIED' if valid else 'UNVERIFIED'
    return fact,verification,None if valid else 'BINDING_INVALID',sha({'fact':fact,'witness':witness,'context':context}) if valid else None


def collect(store,sid,*,limit=32):
    if type(limit) is not int or not 1<=limit<=32:raise ValueError('invalid tool collection limit')
    session = store.get('sessions',sid)
    if not session:return False
    context = _context(sid,session)
    if context is None:return False
    identity = source_id(sid,session['generation']);before = store.get('tool_sources',identity)
    source = dict(before) if before else _source(identity,context)
    if source['status'] in {'QUARANTINED','UNSUPPORTED'}:return False
    old,updates = {},{}
    if (session.get('resources') or {}).get('disk'):
        source.update(status='UNSUPPORTED',reason='DISK_RAW_UNSUPPORTED')
        try:return _commit(store,sid,session,identity,before,source,old,updates)
        except Conflict:return False
    try:
        if source['context']!=context:raise ValueError('tool context changed')
        if not journal.context_valid(context) or not isinstance(sid,str) or session.get('directory')!=str(store.root/'roles'/sid):
            raise ValueError('unanchored tool source')
        path = store.root/'roles'/sid
        with contextlib.ExitStack() as stack:
            parent = os.open(store.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);stack.callback(os.close,parent)
            roles = os.open('roles',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);stack.callback(os.close,roles)
            directory = os.open(sid,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=roles);stack.callback(os.close,directory)
            request = _request(directory,store,sid,session,context)
            try:page = journal.read_page(directory,context,source['cursor'],limit=limit)
            except FileNotFoundError:
                if before is None:return False  # No new-generation journal: unsupported coverage, not zero tools.
                raise
            prefix = identity+':'
            if source['pending_after'] and (not source['pending_after'].startswith(prefix) or not journal.hash_valid(source['pending_after'][len(prefix):])):
                raise ValueError('invalid pending checkpoint')
            pending = _page(store,'tool_receipts','PENDING',source['pending_after'],limit,prefix)
            for rid,value in pending:old[rid]=value;updates[rid]=dict(value)
            for row in page['items']:
                rid = prefix+row['command_digest']
                prior = old.get(rid) or store.get('tool_receipts',rid)
                if prior is not None and prior['semantic_digest']!=semantic(row):raise ValueError('tool registration semantic conflict')
                old[rid] = prior
                updates.setdefault(rid,dict(prior) if prior else _receipt(identity,row))
            launch = None
            try:
                proof = startup_collect(store,sid,session)
                launch = journal.capture_launch(str(path),context)
                if not launch or launch['ack_sha256']!=proof['ack_sha256']:launch = None
            except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError):pass
            for rid,value in updates.items():
                if value['status']!='PENDING':continue
                outcome = _return(directory,path,request,session,context,value['registration'],launch)
                if outcome is not None:
                    fact,verification,reason,validation = outcome
                    value.update(status='COLLECTED',fact=fact,verification=verification,reason=reason,validation_digest=validation)
                    if verification=='VERIFIED':
                        # Freeze lineage from the request validated against this
                        # generation, not from a later mutable session at read time.
                        # Old collected receipts without this field stay unknown;
                        # never silently backfill historical task attribution.
                        value['task_id'] = request['task_id']
                        value['validation_version'] = 2
                        value['validation_digest'] = sha({'fact':fact,'witness':value['registration']['launch_witness'],
                                                          'context':context,'task_id':value['task_id']})
            if pending:source['pending_after']=pending[-1][0]
            source.update(cursor=page['cursor'],incomplete_tail=page['incomplete_tail'],status='ACTIVE',reason=None)
            if session.get('status') not in ACTIVE and not page['has_more'] and not any(v['status']=='PENDING' for v in updates.values()):
                # Check only one indexed remaining PENDING outside this bounded batch.
                with store.connect() as db:
                    marks=','.join('?' for _ in updates)
                    query="SELECT 1 FROM projection WHERE section='tool_receipts' AND object_status='PENDING' AND object_key>=? AND object_key<?"
                    args=[prefix,prefix+'g']
                    if updates:query+=' AND object_key NOT IN ('+marks+')';args+=list(updates)
                    remains=db.execute(query+' LIMIT 1',args).fetchone()
                if not remains:source['status']='DRAINED'
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError) as error:
        source = dict(before) if before else _source(identity,context)
        source.update(status='UNSUPPORTED' if isinstance(error,SourceCapacityError) else 'QUARANTINED',
                      reason='SOURCE_CAPACITY' if isinstance(error,SourceCapacityError) else 'SOURCE_MISSING' if isinstance(error,FileNotFoundError) else 'SOURCE_INVALID')
        old,updates = {},{}
    # Transaction/storage failures are not source corruption: roll back and let
    # the controller retry, never commit QUARANTINED in lieu of the failed data.
    try:return _commit(store,sid,session,identity,before,source,old,updates)
    except Conflict:return False  # Stale competing poll: retry from committed checkpoint.


def scan(store,*,limit=8):
    """Fair global drain keeps terminal sessions with pending returns discoverable."""
    if type(limit) is not int or not 1<=limit<=32:raise ValueError('invalid tool scan limit')
    before = store.get('tool_scan','global');after = before['after'] if before else ''
    rows = _page(store,'tool_sources','ACTIVE',after,limit)
    for _,source in rows:collect(store,source['context']['session'])
    if not rows or rows[-1][0]==after:return len(rows)
    def advance(state):
        if state.get('tool_scan',{}).get('global')!=before:raise Conflict('tool scan checkpoint changed')
        state.setdefault('tool_scan',{})['global']={'after':rows[-1][0],'round':before['round']+1 if before else 1}
    try:store.transact_objects('TOOL_SCAN_CHECKPOINT','tool_scan:'+sha([before,rows[-1][0]]),[('tool_scan','global')],advance,object_id='tool_scan')
    except Conflict:pass
    return len(rows)
