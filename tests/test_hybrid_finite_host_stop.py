"""Actual whole-original-scope STOP; no native/model/GPU invocation."""
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest

from fastapi.testclient import TestClient

from rlflow.hybrid_finite_host_stop import FiniteHostStop,ACTION
from rlflow.store import Conflict
from tests.test_hybrid_finite_host_app import application,ORIGIN,path,start
from tests.test_execution_adapter import setup as native_setup

def test_actual_two_original_Runs_one_live_one_Pool_wait_STOP_before_both_G(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    entered=threading.Event();waiting=threading.Event()
    register=units[0].runtime._register_release
    def held(attempt):
        entered.set();assert units[0]._cancelled.wait(2)
        return register(attempt)
    monkeypatch.setattr(units[0].runtime,'_register_release',held)
    preflight=host._preflight
    def observed(lease,token,body):
        if lease is units[1].lease:waiting.set()
        return preflight(lease,token,body)
    monkeypatch.setattr(host,'_preflight',observed)
    operations=[s.prepare(start(s),token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='two_live_run') for s in services]
    with ThreadPoolExecutor(max_workers=2) as workers:
        jobs=[workers.submit(services[0].execute_prepared,operations[0])]
        assert entered.wait(8)
        jobs.append(workers.submit(services[1].execute_prepared,operations[1]))
        assert waiting.wait(1)
        source=units[0].runtime.sources._issued(units[0].runtime._issued(units[0].lease)['source'])
        assert source['producer'].poll() is None
        assert not units[1].runtime._issued(units[1].lease)['spawn_entered']
        coordinator=app.state.finite_host_stop
        batch=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='two_live_stop')
        result=coordinator.execute_prepared(batch)
        assert result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN',result
        assert jobs[0].result(timeout=10)['status']=='ACCEPTED'
        with pytest.raises(Conflict):jobs[1].result(timeout=10)
        assert all(not u.runtime._issued(u.lease)['release_entered'] for u in units)
        assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
        assert not units[1].runtime._issued(units[1].lease)['spawn_entered']
        assert host.pool.snapshot()['occupied']==0
        print('actual_two_original_Runs_STOP',dict(live_before_STOP=1,other_Pool_wait=True,both_G=False,all_reaped=True,all_FDs_closed=True,occupied=0),flush=True)

def test_actual_whole_auth_and_conflict_before_any_latch_capacity_after_all_latches(application):
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop
    kwargs=dict(token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='bounds')
    versions=[s.store.version() for s in services]
    for changed in ({'token':'missing'},{'csrf':'wrong'},{'origin':'http://127.0.0.1:1'}):
        with pytest.raises(PermissionError):coordinator.prepare({'action':ACTION},**{**kwargs,**changed})
    for body in ({'action':ACTION,'targets':['other']},{'action':'STOP_GOAL'}):
        with pytest.raises(ValueError):coordinator.prepare(body,**kwargs)
    services[1].prepare(start(services[1]),**kwargs)
    with pytest.raises(Conflict,match='idempotency'):coordinator.prepare({'action':ACTION},**kwargs)
    assert not any(u._cancelled.is_set() for u in units)
    assert [s.store.version() for s in services]==versions
    for index in range(32):coordinator.prepare({'action':ACTION},**{**kwargs,'idempotency_key':f'finite_capacity_{index}'})
    with pytest.raises(Conflict,match='capacity'):coordinator.prepare({'action':ACTION},**{**kwargs,'idempotency_key':'overflow'})
    assert all(u._cancelled.is_set() for u in units) and len(coordinator._rows)==32
    assert len(coordinator._safety)==2
    for future in tuple(coordinator._safety.values()):assert future.result(timeout=10)['status']=='CANCELLED_SCOPE_STOPPED'
    assert host.pool.snapshot()['occupied']==0
    assert not any(s.store.objects(s._stop_domain.SECTION) for s in services)
    coordinator.close()
    print('actual_whole_bounds',dict(bad_auth_and_key_conflict_no_latch=True,capacity_rows=32,overflow_all_latched=True,occupied=0,human_STOP_facts=0),flush=True)

def test_actual_pending_future_waiter_interrupt_retains_capacity_and_resumes_only_unknown(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop
    kwargs=dict(token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='pending_interrupt')
    batch=coordinator.prepare({'action':ACTION},**kwargs)
    release=threading.Event();started=threading.Event();finished=threading.Event();futures=[];calls=[]
    scope=coordinator._scope_stop;submit=coordinator._executor.submit
    def held(service,body,operation):
        calls.append(service);started.set();assert release.wait(5)
        return scope(service,body,operation)
    def interrupted(*args,**kw):
        if futures:raise KeyboardInterrupt('injected second submission SDK interruption')
        future=submit(*args,**kw);futures.append(future);return future
    with monkeypatch.context() as patch:
        patch.setattr(coordinator,'_scope_stop',held);patch.setattr(coordinator._executor,'submit',interrupted)
        try:
            with pytest.raises(KeyboardInterrupt):coordinator.execute_prepared(batch)
            assert started.wait(1)
            assert coordinator._active==1 and coordinator._rows[(batch.actor,batch.key)]['running']
            with pytest.raises(Conflict,match='still running'):coordinator.execute_prepared(batch)
        finally:
            futures[0].add_done_callback(lambda _:finished.set());release.set()
            assert finished.wait(10)
    assert coordinator._active==0 and not coordinator._rows[(batch.actor,batch.key)]['running']
    previous=coordinator.execute_prepared(batch)
    assert [r['intent_status'] for r in previous['items']]==['ACCEPTED','UNKNOWN']
    version=services[0].store.version()
    result=coordinator.execute_prepared(batch,_resume_unknown=True)
    assert result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
    assert services[0].store.version()==version and calls==[services[0]] and host.pool.snapshot()['occupied']==0
    coordinator.close()
    print('actual_pending_interrupt',dict(active_until_future_terminal=True,known_scope_not_recleaned=True,occupied=0),flush=True)

def test_actual_partial_executor_submission_refusal_still_cleans_every_scope(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop;submit=coordinator._executor.submit;count=[]
    def refused(*args,**kwargs):
        count.append(True)
        if len(count)==2:raise RuntimeError('injected second executor submission refusal')
        return submit(*args,**kwargs)
    batch=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='partial_submit')
    with monkeypatch.context() as patch:
        patch.setattr(coordinator._executor,'submit',refused)
        result=coordinator.execute_prepared(batch)
    assert result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
    assert len(count)==2 and coordinator._active==0 and host.pool.snapshot()['occupied']==0
    assert all(r['intent_status']=='ACCEPTED' for r in result['items'])
    coordinator.close()
    print('actual_partial_submit',dict(submitted=1,bounded_inline_fallback=1,occupied=0),flush=True)

def test_actual_HTTP_zero_submission_refusal_still_cleans_original_scopes_without_STOP_facts(application,monkeypatch):
    from rlflow.hybrid_control import ControlError
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop
    async def refused(call):raise ControlError(429,'BUDGET_EXHAUSTED','injected zero-submission capacity')
    monkeypatch.setattr(app.state.finite_host_stop_pool,'run',refused)
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        response=client.post('/api/v1/finite-host/commands',headers={**headers,'Idempotency-Key':'refused'},json={'action':ACTION})
        assert response.status_code==429 and all(u._cancelled.is_set() for u in units)
        futures=tuple(coordinator._safety.values());assert len(futures)==2
        results=[future.result(timeout=10) for future in futures]
        assert all(result['status']=='CANCELLED_SCOPE_STOPPED' for result in results)
        assert host.pool.snapshot()['occupied']==0
        assert not any(s.store.objects(s._stop_domain.SECTION) for s in services)
        print('actual_HTTP_zero_submission_safe_cleanup',dict(response=429,all_latched=True,
            cleanup_scopes=2,occupied=0,human_STOP_facts=0),flush=True)

def test_actual_HTTP_independent_whole_scope_STOP_during_original_CPU_Run(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    entered=threading.Event();register=units[0].runtime._register_release
    def waiting(attempt):
        entered.set();assert units[0]._cancelled.wait(2)
        return register(attempt)
    monkeypatch.setattr(units[0].runtime,'_register_release',waiting)
    with TestClient(app,base_url=ORIGIN) as client,ThreadPoolExecutor(max_workers=1) as worker:
        client.cookies.set('rlflow_session',token)
        profile=client.get('/api/v1/finite-host')
        assert profile.status_code==200 and profile.json()['stop_enabled']
        assert len(profile.json()['items'])==2 and not profile.json()['execution_enabled']
        future=worker.submit(client.post,path(services[0])+'/commands',headers=headers,json=start(services[0]))
        assert entered.wait(8)
        body={'action':ACTION};stop_headers={**headers,'Idempotency-Key':'http_finite_stop'}
        response=client.post('/api/v1/finite-host/commands',headers=stop_headers,json=body)
        assert response.status_code==202,response.text
        assert future.result(timeout=10).status_code==202
        result=response.json();assert result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
        assert host.pool.snapshot()['occupied']==0 and all(u._cancelled.is_set() for u in units)
        source=units[0].runtime.sources._issued(units[0].runtime._issued(units[0].lease)['source'])
        assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
        before=[s.store.version() for s in services]
        assert client.get('/api/v1/finite-host/commands/'+result['command_id']).json()['duplicate']
        assert client.post('/api/v1/finite-host/commands',headers=stop_headers,json=body).json()['duplicate']
        assert [s.store.version() for s in services]==before
        assert not result['goal_completed'] and not result['durable_aggregate_receipt']
        print('actual_HTTP_finite_STOP',dict(scopes=2,cpu_G=False,occupied=0,
            independent_from_original_Run=True,receipt_retry_no_writes=True),flush=True)

def test_actual_whole_scope_latch_before_IO_single_preG_worker_and_receipt_only_retry(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop
    cpu,engineering=units;entered=threading.Event();register=cpu.runtime._register_release
    def waiting(attempt):
        entered.set();assert cpu._cancelled.wait(2)
        return register(attempt)
    monkeypatch.setattr(cpu.runtime,'_register_release',waiting)
    calls=[]
    for unit in units:
        cancel=unit.cancel
        def all_latched(_cancel=cancel,_unit=unit):
            assert all(u._cancelled.is_set() for u in units)
            calls.append(_unit);return _cancel()
        monkeypatch.setattr(unit,'cancel',all_latched)
    try:
        with TestClient(app,base_url=ORIGIN) as client,ThreadPoolExecutor(max_workers=1) as worker:
            client.cookies.set('rlflow_session',token)
            future=worker.submit(client.post,path(services[0])+'/commands',headers=headers,json=start(services[0]))
            assert entered.wait(8)
            batch=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],
                origin=ORIGIN,idempotency_key='whole_stop')
            assert all(u._cancelled.is_set() for u in units)
            result=coordinator.execute_prepared(batch)
            assert future.result(timeout=10).status_code==202
            assert result['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN',result
            assert result['durable_aggregate_receipt'] is False and result['goal_completed'] is False
            assert len(result['items'])==2 and all(r['intent_status']=='ACCEPTED' for r in result['items'])
            attempt=cpu.runtime._issued(cpu.lease);source=cpu.runtime.sources._issued(attempt['source'])
            assert not attempt['release_entered'] and source['producer'].poll() is not None
            assert all(fd is None for fd in source['fds'].values())
            assert not engineering.runtime._issued(engineering.lease)['spawn_entered']
            assert host.pool.snapshot()['occupied']==0
            versions=[s.store.version() for s in services];count=len(calls)
            retry=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],
                origin=ORIGIN,idempotency_key='whole_stop')
            assert coordinator.execute_prepared(retry)['duplicate'] is True
            assert len(calls)==count and [s.store.version() for s in services]==versions
            print('actual_finite_STOP',dict(original_scopes=2,all_latched_before_cleanup=True,
                cpu_G=False,other_spawn=False,occupied=0,duplicate_cleanup=False),flush=True)
    finally:coordinator.close()

def test_actual_reverse_unknown_resume_interruption_preserves_known_later_scope(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop
    calls=[]
    for unit in units:
        cancel=unit.cancel
        def counted(_cancel=cancel,_unit=unit):calls.append(_unit);return _cancel()
        monkeypatch.setattr(unit,'cancel',counted)
    try:
        with monkeypatch.context() as failure:
            failure.setattr(units[0],'_cleanup',lambda:{'complete':False,'error':'injected CPU cleanup unavailable'})
            batch=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],
                origin=ORIGIN,idempotency_key='reverse_partial')
            result=coordinator.execute_prepared(batch)
        assert [r['cleanup_status'] for r in result['items']]==['UNKNOWN','ORIGINAL_SCOPE_STOPPED']
        assert host.pool.snapshot()['occupied']==1
        with monkeypatch.context() as interrupted:
            def abort(*args,**kwargs):raise KeyboardInterrupt('injected original SDK waiter interruption')
            interrupted.setattr(coordinator._executor,'submit',abort)
            with pytest.raises(KeyboardInterrupt):coordinator.execute_prepared(batch,_resume_unknown=True)
        cached=coordinator.execute_prepared(batch)
        assert [r['cleanup_status'] for r in cached['items']]==['UNKNOWN','ORIGINAL_SCOPE_STOPPED']
        assert len(calls)==2
        finished=coordinator.execute_prepared(batch,_resume_unknown=True)
        assert finished['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN',finished
        assert calls.count(units[0])==2 and calls.count(units[1])==1 and host.pool.snapshot()['occupied']==0
        print('actual_reverse_unknown_interrupted_resume',dict(known_scope_preserved=True,
            known_scope_not_recleaned=True,occupied=0),flush=True)
    finally:coordinator.close()

def test_actual_partial_cleanup_mutated_reply_cannot_hide_unknown_and_explicit_original_resume(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop
    calls=[]
    for unit in units:
        cancel=unit.cancel
        def counted(_cancel=cancel,_unit=unit):calls.append(_unit);return _cancel()
        monkeypatch.setattr(unit,'cancel',counted)
    try:
        with monkeypatch.context() as failure:
            failure.setattr(units[1],'_cleanup',lambda:{'complete':False,'error':'injected original cleanup unavailable'})
            batch=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],
                origin=ORIGIN,idempotency_key='partial_stop')
            result=coordinator.execute_prepared(batch)
        assert result['status']=='PARTIAL_OR_UNKNOWN' and host.pool.snapshot()['occupied']==1
        assert [r['cleanup_status'] for r in result['items']]==['ORIGINAL_SCOPE_STOPPED','UNKNOWN']
        # Returned nested JSON is not authority or the retained private cache.
        result['status']='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
        result['items'][1].update(intent_status='ACCEPTED',cleanup_status='ORIGINAL_SCOPE_STOPPED',post_cleanup_status='RETURNED')
        again=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],
            origin=ORIGIN,idempotency_key='partial_stop')
        cached=coordinator.execute_prepared(again)
        assert cached['duplicate'] and cached['status']=='PARTIAL_OR_UNKNOWN'
        assert cached['items'][1]['cleanup_status']=='UNKNOWN' and len(calls)==2
        versions=[s.store.version() for s in services]
        intents=[s.store.objects(s._stop_domain.SECTION) for s in services]
        resumed=coordinator.execute_prepared(again,_resume_unknown=True)
        assert resumed['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN',resumed
        assert calls.count(units[0])==1 and calls.count(units[1])==2
        assert host.pool.snapshot()['occupied']==0
        assert services[0].store.version()==versions[0] and services[1].store.version()>versions[1]
        assert [s.store.objects(s._stop_domain.SECTION) for s in services]==intents
        print('actual_finite_partial_resume',dict(initial_occupied=1,remaining_unknown=True,
            mutated_JSON_not_authority=True,only_unknown_cleanup_resumed=True,occupied=0),flush=True)
    finally:coordinator.close()
