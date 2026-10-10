import time
import json
import select
import subprocess
import sys
import os
import sqlite3
from contextlib import closing
import pytest
import httpx
from rlflow.observation import enable, ObservationReader
from rlflow.store import Store
from rlflow.jobs import owns
from tests.acceptance_http_v1 import launch_api, finish
from tests.acceptance_http_v1 import measure_http, schedule


def test_owned_fixture_api_requires_real_authenticated_readiness(tmp_path):
    store=Store(tmp_path/'state');enable(store,'project_http_probe',data_mode='fixture')
    head=ObservationReader(store.root).head();log=tmp_path/'api.log'
    child,packet=launch_api(store.root,log)
    try:
        deadline=time.monotonic()+10;snapshot=None
        with httpx.Client(base_url=packet['origin'],headers={'Authorization':'Bearer '+packet['token']},timeout=1) as client:
            while snapshot is None:
                try:
                    response=client.get('/api/v1/projects/project_http_probe/snapshot')
                    response.raise_for_status();snapshot=response.json()
                except httpx.ConnectError:
                    if time.monotonic()>=deadline:raise
                    time.sleep(.02)
            assert snapshot['project_id']==head['project_id'] and snapshot['data_mode']=='fixture'
            assert snapshot['store_epoch']==head['cursor'].rsplit(':',1)[0] and snapshot['cursor']==head['cursor']
            response=client.get('/api/v1/projects/project_http_probe/snapshot',headers={'Authorization':'Bearer invalid'})
            assert response.status_code==401
    finally:finish(child)
    assert child.poll() is not None and not owns(packet['identity']) and log.stat().st_size==0


def test_api_parent_sigkill_after_real_ready_leaves_no_running_server(tmp_path):
    store=Store(tmp_path/'state');enable(store,'project_http_death',data_mode='fixture')
    program=r'''
import json,sys,time,httpx
from tests.acceptance_http_v1 import launch_api
child,packet=launch_api(sys.argv[1],sys.argv[2])
deadline=time.monotonic()+10
with httpx.Client(base_url=packet['origin'],headers={'Authorization':'Bearer '+packet['token']},timeout=1) as client:
    while True:
        try:
            response=client.get('/api/v1/projects/project_http_death/snapshot');response.raise_for_status();break
        except httpx.ConnectError:
            if time.monotonic()>=deadline:raise
            time.sleep(.02)
print(json.dumps(packet['identity']),flush=True)
time.sleep(30)
'''
    parent=subprocess.Popen([sys.executable,'-u','-c',program,str(store.root),str(tmp_path/'api.log')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert select.select([parent.stdout],[],[],15)[0],'authenticated API readiness missing'
        record=json.loads(parent.stdout.readline())
        assert owns(record)
        parent.kill();parent.wait(5)
        deadline=time.monotonic()+5
        while owns(record) and time.monotonic()<deadline:time.sleep(.02)
        assert not owns(record)
    finally:
        if parent.poll() is None:parent.kill();parent.wait(5)
        parent.stdout.close();parent.stderr.close()


def test_socket_setup_failure_closes_private_pipe(tmp_path,monkeypatch):
    from tests import acceptance_http_v1 as probe
    descriptors=[];original=os.pipe
    def pipe():
        result=original();descriptors.extend(result);return result
    def failed(*args,**kwargs):raise OSError('injected socket allocation failure')
    with monkeypatch.context() as patch:
        patch.setattr(probe.os,'pipe',pipe);patch.setattr(probe.socket,'socket',failed)
        with pytest.raises(OSError,match='allocation'):probe.launch_api(tmp_path,tmp_path/'unused.log')
    for fd in descriptors:
        with pytest.raises(OSError):os.fstat(fd)


def test_absolute_schedule_indices_and_limits():
    plan,duration=schedule(((10,30),(50,2)))
    assert duration==32 and len(plan)==400
    assert [row['index'] for row in plan]==list(range(400))
    assert plan[300]['offset']==30 and plan[-1]['offset']==31.98
    with pytest.raises(ValueError):schedule(((51,2),))


def test_finite_real_http_concurrency_matches_outbox(tmp_path):
    source=Store(tmp_path/'source');enable(source,'project_http_small',data_mode='fixture')
    for i in range(1,5):
        source.transact_objects('USAGE_OBSERVED',str(i),[('usage','fixed')],lambda s,v=i:s.setdefault('usage',{}).update(fixed={'input_tokens':v}))
    # Keep the live fixture WAL owned for the measured interval. A SQLite
    # context manager commits but does not close; GC of setup connections can
    # otherwise checkpoint the source bytes without any business mutation.
    with closing(sqlite3.connect(source.db.as_uri()+'?mode=ro',uri=True)) as pin:
        pin.execute('SELECT version FROM projection_meta').fetchone()
        result=measure_http(source.db,tmp_path/'probe',tasks=2,min_events=4,phases=((2,1),))
    assert result['public_events']==2 and result['source_unchanged'] and not result['full_B1_pass']
    assert len(result['raw']['writes'])==2 and len(result['raw']['queries'])==4
    assert all(len(rows)==2 for rows in result['raw']['receivers'])
    assert all(len(rows)==1 for rows in result['raw']['reconnects'])
    assert len(result['latencies'])==4
    assert result['core_events']==7 and result['tasks']==2 and result['sessions']==0
    assert result['phases'][0]['actual_writes']==result['phases'][0]['planned_writes']==2
    assert len(result['raw']['query_plan'])==4


@pytest.mark.parametrize('stage',['exercise','summarize'])
def test_failures_preserve_raw_and_reap_owned_api(tmp_path,monkeypatch,capsys,stage):
    from tests import acceptance_http_v1 as probe
    source=Store(tmp_path/'source');enable(source,'project_http_failure',data_mode='fixture')
    source.transact_objects('USAGE_OBSERVED','1',[('usage','fixed')],lambda s:s.setdefault('usage',{}).update(fixed={'input_tokens':1}))
    launched=[];original=probe.launch_api
    def launch(*args):
        result=original(*args);launched.append(result);return result
    async def exercise(*args):raise RuntimeError('injected exercise failure')
    def summarize(*args):raise RuntimeError('injected final validation failure')
    monkeypatch.setattr(probe,'launch_api',launch)
    monkeypatch.setattr(probe,stage,exercise if stage=='exercise' else summarize)
    with pytest.raises(RuntimeError,match='injected'):
        probe.measure_http(source.db,tmp_path/'probe',tasks=1,min_events=1,phases=((2,1),))
    child,packet=launched[0];output=capsys.readouterr().out
    assert child.poll() is not None and not owns(packet['identity'])
    assert packet['token'] not in output and packet['origin'] not in output
    failure=json.loads(output.splitlines()[-1]);assert failure['failure']=='RuntimeError' and 'raw' in failure


def test_optimized_probe_rejects_before_creating_fixture(tmp_path):
    output=tmp_path/'unused'
    result=subprocess.run([sys.executable,'-O','-m','tests.acceptance_http_v1',str(tmp_path/'missing'),str(output)],capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and 'optimized acceptance probes are unsupported' in result.stderr
    assert not output.exists()


def test_missing_public_write_coverage_fails_final_validation(tmp_path,monkeypatch,capsys):
    from tests import acceptance_http_v1 as probe
    source=Store(tmp_path/'source');enable(source,'project_http_coverage',data_mode='fixture')
    source.transact_objects('USAGE_OBSERVED','1',[('usage','fixed')],lambda s:s.setdefault('usage',{}).update(fixed={'input_tokens':1}))
    original=probe.summarize
    def missing(store,*args):
        with store.connect() as db:
            # Deliberately corrupt only this disposable test clone, after API
            # cleanup, to model a bridge omission; production guard stays intact.
            db.execute('DROP TRIGGER observation_no_delete')
            db.execute("DELETE FROM observation_events WHERE source_event_id IN (SELECT event_id FROM events WHERE idempotency_key='http-0')")
        return original(store,*args)
    monkeypatch.setattr(probe,'summarize',missing)
    with pytest.raises(RuntimeError,match='outbox omits planned writes'):
        probe.measure_http(source.db,tmp_path/'probe',tasks=1,min_events=1,phases=((2,1),))
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['failure']=='RuntimeError'


@pytest.mark.parametrize('bad',['content_type','domain'])
def test_bad_sse_preserves_reason_and_reaps_api(tmp_path,monkeypatch,capsys,bad):
    from tests import acceptance_http_v1 as probe
    source=Store(tmp_path/'source');enable(source,'project_http_bad_sse',data_mode='fixture')
    source.transact_objects('USAGE_OBSERVED','1',[('usage','fixed')],lambda s:s.setdefault('usage',{}).update(fixed={'input_tokens':1}))
    wrapper=probe.API_WRAPPER
    injected="""
from starlette.responses import StreamingResponse
async def bad_stream():
    yield 'event: domain\\ndata: {}\\n\\n'
    import asyncio
    await asyncio.sleep(60)
async def bad_endpoint(request):
    return StreamingResponse(bad_stream(),media_type=BAD_TYPE)
for route in app.routes:
    if getattr(route,'path','').endswith('/events'):
        route.endpoint=bad_endpoint
        from starlette.routing import request_response
        route.app=request_response(bad_endpoint)
""".replace('BAD_TYPE',repr('text/plain' if bad=='content_type' else 'text/event-stream'))
    monkeypatch.setattr(probe,'API_WRAPPER',wrapper.replace('packet={',injected+'\npacket={'))
    launched=[];original=probe.launch_api
    def launch(*args):
        result=original(*args);launched.append(result);return result
    monkeypatch.setattr(probe,'launch_api',launch)
    with pytest.raises((RuntimeError,KeyError)):
        probe.measure_http(source.db,tmp_path/'probe',tasks=1,min_events=1,phases=((2,1),))
    failure=json.loads(capsys.readouterr().out.splitlines()[-1]);errors=failure['raw']['receiver_errors']
    assert any(r and r['error']==('RuntimeError' if bad=='content_type' else 'KeyError') for r in errors)
    if bad=='domain':assert any(r and 'data: {}' in r['last_frame'] for r in errors)
    child,packet=launched[0];assert child.poll() is not None and not owns(packet['identity'])


@pytest.mark.parametrize('stage',['before_cleanup','exit_code'])
def test_api_abnormal_exit_cannot_be_reported_as_success(tmp_path,monkeypatch,capsys,stage):
    from tests import acceptance_http_v1 as probe
    source=Store(tmp_path/'source');enable(source,'project_http_exit',data_mode='fixture')
    source.transact_objects('USAGE_OBSERVED','1',[('usage','fixed')],lambda s:s.setdefault('usage',{}).update(fixed={'input_tokens':1}))
    original_exercise=probe.exercise;original_summary=probe.summarize
    async def exercise(store,packet,manifest,plan,duration,raw,child,log):
        await original_exercise(store,packet,manifest,plan,duration,raw,child,log)
        child.kill();child.wait(5)
    def summarize(*args):return original_summary(*args[:-1],-9)
    monkeypatch.setattr(probe,'exercise' if stage=='before_cleanup' else 'summarize',exercise if stage=='before_cleanup' else summarize)
    with pytest.raises(RuntimeError,match='cleanup|abnormal exit'):
        probe.measure_http(source.db,tmp_path/'probe',tasks=1,min_events=1,phases=((2,1),))
    failure=json.loads(capsys.readouterr().out.splitlines()[-1]);assert failure['failure']=='RuntimeError'
