"""Owned loopback API infrastructure for a finite fixture probe; NOT full B1."""
import json
import os
import asyncio
import hashlib
import math
import time
from pathlib import Path
import select
import socket
import subprocess
import sys
import threading
from rlflow.jobs import identity, owns
from tests.acceptance_idle_v1 import WRAPPER, finish
from tests.acceptance_idle_v1 import prepare, fingerprint
from tests.acceptance_history_v1 import percentile
from rlflow.observation import ObservationReader, public_id
from rlflow.policy import stopped
from rlflow.store import canonical
from tests.acceptance_tasks_v1 import task as fixture_task
import httpx


# Keep the reviewed parent witness and setup-race checks. Uvicorn installs a
# SIGTERM handler, so parent-death uses SIGKILL; normal cleanup is still bounded
# SIGTERM -> SIGKILL -> reap. Never pass authentication material in argv/logs.
_READY_MARKER='os.write(int(sys.argv[3])'
_DEATH_GUARD='libc.prctl(1,signal.SIGTERM,0,0,0)'
if WRAPPER.count(_READY_MARKER)!=1 or WRAPPER.count(_DEATH_GUARD)!=1:
    raise RuntimeError('reviewed parent guard template changed')
API_WRAPPER=WRAPPER.split(_READY_MARKER,1)[0].replace(
    _DEATH_GUARD, 'libc.prctl(1,signal.SIGKILL,0,0,0)')+r'''
import socket,uvicorn
from rlflow.observation import ObservationReader
from rlflow.web_api import Project,create_app
from rlflow.web_auth import AuthStore,Principal
sock=socket.socket(fileno=int(sys.argv[4]))
host,port=sock.getsockname()
if host!='127.0.0.1':raise RuntimeError('API socket is not loopback')
head=ObservationReader(sys.argv[1]).head()
if head['data_mode']!='fixture':raise RuntimeError('API probe requires fixture')
auth=AuthStore()
token,_=auth.issue_bearer(Principal('fixture_probe','agent',frozenset({'viewer'}),frozenset({head['project_id']})))
origin=f'http://127.0.0.1:{port}'
app=create_app([Project(head['project_id'],sys.argv[1],'fixture')],auth,origin=origin)
packet={'identity':witness(os.getpid()),'origin':origin,'token':token,'head':head}
os.write(int(sys.argv[3]),(json.dumps(packet)+'\n').encode());os.close(int(sys.argv[3]))
server=uvicorn.Server(uvicorn.Config(app,host=host,port=port,proxy_headers=False,access_log=False,log_level='error',timeout_graceful_shutdown=2))
server.run(sockets=[sock])
'''


def launch_api(state,log):
    """Private readiness packet is not yet an authenticated HTTP readiness proof.

    Caller must GET and validate the real snapshot before issuing any load.
    The returned token must never be printed, logged or saved in evidence.
    """
    if sys.flags.optimize:raise RuntimeError('optimized acceptance probes are unsupported')
    if threading.current_thread() is not threading.main_thread():raise RuntimeError('launch requires stable main thread')
    read,write=os.pipe();child=None
    sock=None
    try:
        sock=socket.socket()
        sock.bind(('127.0.0.1',0));origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
        with Path(log).open('xb') as stream:
            child=subprocess.Popen([sys.executable,'-u','-c',API_WRAPPER,str(state),json.dumps(identity(os.getpid())),str(write),str(sock.fileno())],
                stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,pass_fds=(write,sock.fileno()),start_new_session=True)
        os.close(write);write=None
        if not select.select([read],[],[],10)[0]:raise RuntimeError('API guard readiness timeout')
        packet=json.loads(os.read(read,4096));record=packet['identity']
        if record['pid']!=child.pid or not owns(record) or packet['origin']!=origin:raise RuntimeError('API readiness mismatch')
        return child,packet
    except BaseException:
        if child is not None:finish(child)
        raise
    finally:
        if sock is not None:sock.close()
        os.close(read)
        if write is not None:os.close(write)


def schedule(phases):
    """Absolute plan, never paced relative to completion of the previous write."""
    rows=[];offset=0
    for index,(rate,seconds) in enumerate(phases):
        if type(rate) is not int or not 1<=rate<=50 or type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=30:
            raise ValueError('invalid HTTP profile')
        count=int(rate*seconds)
        if not count:raise ValueError('empty phase')
        base_index=len(rows)
        rows.extend({'index':base_index+i,'phase':index,'offset':offset+i/rate} for i in range(count))
        offset+=seconds
    if not rows or len(rows)>1000 or offset>60:raise ValueError('invalid total HTTP profile')
    return rows,offset


async def exercise(store,packet,manifest,plan,duration,raw,child,log):
    project=packet['head']['project_id'];base=f'/api/v1/projects/{project}'
    headers={'Authorization':'Bearer '+packet['token']};epoch=manifest['cursor'].rsplit(':',1)[0]
    baseline_seq=int(manifest['cursor'].rsplit(':',1)[1]);ready=[asyncio.Event(),asyncio.Event()]
    done=asyncio.Event();final=[None];tasks=[]
    async with httpx.AsyncClient(base_url=packet['origin'],headers=headers,timeout=10) as client:
        deadline=time.monotonic()+10
        while True:
            try:
                response=await client.get(base+'/snapshot');response.raise_for_status();snapshot=response.json();break
            except httpx.ConnectError:
                if time.monotonic()>=deadline:raise
                await asyncio.sleep(.02)
        if (snapshot['project_id']!=project or snapshot['data_mode']!='fixture' or snapshot['store_epoch']!=epoch or snapshot['cursor']!=manifest['cursor'] or snapshot['projection']['source_state_version']!=manifest['core_version']):
            raise RuntimeError('real authenticated API readiness mismatch')
        async def receive_stream(index):
            cursor=manifest['cursor'];reconnected=False;rows=raw['receivers'][index]
            # Each consumer has its own TCP pool; never multiplex one stream.
            async with httpx.AsyncClient(base_url=packet['origin'],headers=headers,timeout=10) as stream_client:
                while True:
                    request_headers={'Last-Event-ID':cursor} if reconnected else {}
                    params={'after':'invalid' if reconnected else cursor}
                    async with stream_client.stream('GET',base+'/events',params=params,headers=request_headers) as response:
                        raw['connections'][index].append({'cursor':cursor,'reconnected':reconnected,'status':response.status_code,'content_type':response.headers.get('content-type','')[:256],'opened':time.monotonic()})
                        response.raise_for_status()
                        if response.status_code!=200 or response.headers.get('content-type','').split(';',1)[0]!='text/event-stream':
                            raise RuntimeError('SSE response is not an event stream')
                        ready[index].set();frame=[]
                        async for line in response.aiter_lines():
                            if line:
                                frame.append(line)
                                if len(frame)>128 or sum(len(item) for item in frame)>2*1024*1024:raise RuntimeError('oversize SSE frame')
                                continue
                            received=time.monotonic();fields={}
                            raw['last_frames'][index]=[item[:1024] for item in frame[:8]]
                            for item in frame:
                                if ': ' in item:
                                    key,value=item.split(': ',1);fields[key]=value
                            frame=[];kind=fields.get('event')
                            if kind=='domain':
                                value=json.loads(fields['data']);seq=value['seq']
                                expected=baseline_seq+len(rows)+1
                                if seq!=expected or value['store_epoch']!=epoch or fields.get('id')!=f'{epoch}:{seq}':raise RuntimeError('SSE gap/duplicate/identity mismatch')
                                cursor=fields['id'];rows.append({'received':received,'event':value,'cursor':cursor})
                                if not reconnected:
                                    reconnected=True;raw['reconnects'][index].append({'cursor':cursor,'time':received});break
                            elif kind=='resync_required':raise RuntimeError('unexpected SSE resync')
                            elif kind in ('heartbeat','telemetry'):
                                if 'id' in fields:raise RuntimeError('optional frame carries durable ID')
                            else:raise RuntimeError('unexpected SSE frame')
                            if done.is_set() and rows and rows[-1]['event']['seq']==final[0]:return
                        else:raise RuntimeError('SSE ended before final cursor')
        async def receive(index):
            try:await receive_stream(index)
            except Exception as exc:
                raw['receiver_errors'][index]={'error':type(exc).__name__,'reason':str(exc)[:256],
                    'last_frame':raw['last_frames'][index]}
                raise
        async def requests(index,start):
            async with httpx.AsyncClient(base_url=packet['origin'],headers=headers,timeout=10) as query_client:
                for i in range(math.ceil(duration/.5)):
                    target=start+i*.5;await asyncio.sleep(max(0,target-time.monotonic()))
                    path=base+('/snapshot' if i%2==0 else '/objects?kind=task&limit=50')
                    issued=time.monotonic();row={'client':index,'planned':target,'issued':issued,'path':path}
                    raw['queries'].append(row)
                    try:
                        response=await query_client.get(path);row.update(returned=time.monotonic(),status=response.status_code,bytes=len(response.content))
                        response.raise_for_status();value=response.json()
                        if value['project_id']!=project or value['data_mode']!='fixture':raise RuntimeError('HTTP identity mismatch')
                    except Exception as exc:row['error']=type(exc).__name__;raise
        try:
            tasks=[asyncio.create_task(receive(i)) for i in range(2)]
            deadline=time.monotonic()+10
            while not all(event.is_set() for event in ready):
                for task in tasks:
                    if task.done():task.result()
                if time.monotonic()>=deadline:raise RuntimeError('SSE HTTP readiness timeout')
                await asyncio.sleep(.01)
            start=time.monotonic()+.1;raw['start']=start
            raw['query_plan']=[{'client':index,'planned':start+i*.5,
                'path':base+('/snapshot' if i%2==0 else '/objects?kind=task&limit=50')}
                for index in range(2) for i in range(math.ceil(duration/.5))]
            queries=[asyncio.create_task(requests(i,start)) for i in range(2)];tasks.extend(queries)
            for item in plan:
                target=start+item['offset'];await asyncio.sleep(max(0,target-time.monotonic()))
                if stopped(store.root) or child.poll() is not None or not owns(packet['identity']) or log.stat().st_size:
                    raise RuntimeError('STOP, API diagnostic or child death observed')
                for task in tasks:
                    if task.done():task.result()
                key=f'http-{item["index"]}';row={**item,'key':key,'planned':target,'submitted':time.monotonic()};raw['writes'].append(row)
                try:
                    value=manifest['core_version']+item['index']+1
                    result=await asyncio.to_thread(store.transact_objects,'USAGE_OBSERVED',key,[('usage','fixed')],lambda s,v=value:s.setdefault('usage',{}).update(fixed={'input_tokens':v}))
                    row.update(returned=time.monotonic(),version=result['version'],duplicate=result['duplicate'])
                except Exception as exc:row['error']=type(exc).__name__;raise
            final[0]=int(ObservationReader(store.root).head()['cursor'].rsplit(':',1)[1]);done.set()
            await asyncio.wait_for(asyncio.gather(*tasks),15)
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)


def measure_http(source,output,*,tasks=10000,min_events=100000,phases=((10,30),(50,2))):
    if sys.flags.optimize:raise RuntimeError('optimized acceptance probes are unsupported')
    plan,duration=schedule(phases)
    store,manifest=prepare(source,output,tasks=tasks,min_events=min_events)
    if stopped(store.root):raise RuntimeError('STOP engaged')
    log=Path(output)/'api.log';child,packet=launch_api(store.root,log)
    raw={'plan':plan,'writes':[],'queries':[],'receivers':[[],[]],'reconnects':[[],[]],'connections':[[],[]],
        'receiver_errors':[None,None],'last_frames':[[],[]]}
    try:
        try:
            # Token and origin are intentionally absent from the evidence manifest.
            print(json.dumps({'manifest':manifest,'api_identity':packet['identity'],'phases':phases,'sse_options':'production defaults','scope':'single archived fixture; HTTP transport only'}),flush=True)
            async def run_owned():
                try:
                    await asyncio.wait_for(exercise(store,packet,manifest,plan,duration,raw,child,log),duration+30)
                    if child.poll() is not None or not owns(packet['identity']):raise RuntimeError('API died before planned cleanup')
                    raw['pre_cleanup_alive']=True
                # Cancelled to_thread writes may still commit. Reap API before
                # asyncio.run waits for the executor; this is not a hard CLI
                # deadline and cancellation is never claimed to roll back.
                finally:finish(child)
            asyncio.run(run_owned())
        finally:exit_code=finish(child)
        result=summarize(store,source,manifest,plan,raw,packet['identity'],log,exit_code)
        print(json.dumps({'summary':result}),flush=True);return result
    except BaseException as exc:
        print(json.dumps({'failure':type(exc).__name__,'raw':raw}),flush=True);raise


def summarize(store,source,manifest,plan,raw,record,log,exit_code):
    """Validate the final database before reducing any successful samples."""
    if log.stat().st_size or owns(record) or stopped(store.root):raise RuntimeError('API diagnostic, live child or STOP')
    if raw.get('pre_cleanup_alive') is not True or exit_code not in (0,-15):raise RuntimeError('API abnormal exit or unproven planned cleanup')
    with store.connect() as db:
        core_count=db.execute('SELECT count(*) FROM events').fetchone()[0]
        expected=[{'event':json.loads(body),'key':key,'digest':digest,'core_version':version,'source_event_id':event_id} for body,key,digest,version,event_id in db.execute(
            'SELECT o.envelope,e.idempotency_key,o.digest,e.new_state_version,e.event_id FROM observation_events o JOIN events e ON e.event_id=o.source_event_id WHERE o.seq>? ORDER BY o.seq',(int(manifest['cursor'].rsplit(':',1)[1]),))]
    by_key={row['key']:row for row in raw['writes']}
    if len(by_key)!=len(plan) or core_count!=manifest['core_version']+len(plan) or store.version()!=core_count:raise RuntimeError('missing writes/core versions')
    if len(raw['writes'])!=len(plan):raise RuntimeError('duplicate write samples')
    for planned in plan:
        write=by_key.get(f'http-{planned["index"]}')
        if write is None or any(write[k]!=planned[k] for k in ('index','phase','offset')) or write.get('duplicate') is not False or write.get('version')!=manifest['core_version']+planned['index']+1:
            raise RuntimeError('write plan/version mismatch')
    if {r['key'] for r in expected}!=set(by_key):raise RuntimeError('public outbox omits planned writes')
    for actual in expected:
        payload=actual['event']['payload']
        if actual['core_version']!=by_key[actual['key']]['version'] or payload['source_state_version']!=actual['core_version'] or payload['source_event_id']!=public_id(actual['source_event_id']):
            raise RuntimeError('public/core source mismatch')
    latencies=[]
    for index,rows in enumerate(raw['receivers']):
        if len(rows)!=len(expected):raise RuntimeError('missing public events')
        for received,actual in zip(rows,expected):
            if received['event']!=actual['event'] or hashlib.sha256(canonical(actual['event'])).hexdigest()!=actual['digest']:raise RuntimeError('outbox/body mismatch')
            write=by_key[actual['key']]
            latencies.append({'client':index,'phase':write['phase'],'seq':actual['event']['seq'],
                'submit_to_frame_ms':1000*(received['received']-write['submitted']),
                'commit_return_to_frame_ms':1000*(received['received']-write['returned'])})
    records=store.objects('tasks')
    if len(records)!=manifest['tasks'] or any(value!=fixture_task(key) for key,value in records):raise RuntimeError('fixture tasks changed')
    if fingerprint(Path(source).resolve())!=manifest['source_fingerprint'] or store.objects('sessions'):raise RuntimeError('source/session changed')
    # Query count follows the explicit planned duration, not a successful subset.
    planned_queries=sorted((r['client'],r['planned'],r['path']) for r in raw['query_plan'])
    actual_queries=sorted((r['client'],r['planned'],r['path']) for r in raw['queries'])
    if actual_queries!=planned_queries or any('returned' not in r or 'error' in r for r in raw['queries']):raise RuntimeError('incomplete HTTP query')
    snapshot_times=[1000*(r['returned']-r['issued']) for r in raw['queries'] if r['path'].endswith('/snapshot')]
    page_times=[1000*(r['returned']-r['issued']) for r in raw['queries'] if not r['path'].endswith('/snapshot')]
    phase_stats=[]
    for phase in sorted({r['phase'] for r in plan}):
        writes=[r for r in raw['writes'] if r['phase']==phase]
        frames=[r['submit_to_frame_ms'] for r in latencies if r['phase']==phase]
        lag=[1000*(r['submitted']-r['planned']) for r in writes]
        commit=[1000*(r['returned']-r['submitted']) for r in writes]
        phase_stats.append({'phase':phase,'planned_writes':sum(r['phase']==phase for r in plan),'actual_writes':len(writes),
            'issuance_lag_p95_ms':percentile(lag,.95),'issuance_lag_max_ms':max(lag),
            'commit_call_p95_ms':percentile(commit,.95),'submit_to_frame_p95_ms':percentile(frames,.95),
            'submit_to_frame_max_ms':max(frames)})
    result={'raw':raw,'latencies':latencies,'phases':phase_stats,'public_events':len(expected),'core_events':core_count,'tasks':len(records),'sessions':0,'exit_code':exit_code,'source_unchanged':True,
        'submit_to_frame_p95_ms':percentile([r['submit_to_frame_ms'] for r in latencies],.95),
        'snapshot_p95_ms':percentile(snapshot_times,.95) if snapshot_times else None,
        'page_p95_ms':percentile(page_times,.95) if page_times else None,
        'full_B1_pass':False,'scope':'single archived fixture; submit->HTTP frame upper bound, not browser visibility; commit-return deltas may be negative'}
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('output')
    parser.add_argument('--tasks',type=int,default=10000);parser.add_argument('--min-events',type=int,default=100000)
    parser.add_argument('--steady-seconds',type=float,default=30);parser.add_argument('--burst-seconds',type=float,default=2)
    args=parser.parse_args();measure_http(args.source,args.output,tasks=args.tasks,min_events=args.min_events,phases=((10,args.steady_seconds),(50,args.burst_seconds)))
