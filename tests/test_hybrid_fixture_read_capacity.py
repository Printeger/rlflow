"""Public source-proof capacity follows workers, independently of STOP."""
import asyncio
import threading

import httpx
import pytest

from tests.test_hybrid_fixture_runtime import runtime, native_setup
from tests.test_hybrid_fixture_runtime_control import setup, ORIGIN


def test_http_cancel_keeps_read_capacity_stop_independent_and_lifespan_drains(runtime, monkeypatch):
    owner, lease, service, app, token, headers, path, body = setup(runtime)
    pool = app.state.hybrid_fixture_read_pool
    base = path.rsplit('/', 2)[0]
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()
    lock = threading.Lock()
    original = service.reader.tasks
    calls = []
    def held(*args, **kwargs):
        with lock:
            index = len(calls); calls.append(index)
        assert index < 2
        entered[index].set()
        assert release.wait(10), 'test must release actual source workers'
        return original(*args, **kwargs)

    async def scenario():
        waiting = []; closing = None
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                    cookies={'rlflow_session':token}) as client:
                start = await client.post(path, headers=headers, json=body)
                assert start.status_code == 202, start.text
                monkeypatch.setattr(service.reader, 'tasks', held)
                for event in entered:
                    waiting.append(asyncio.create_task(client.get(base)))
                    assert await asyncio.to_thread(event.wait, 2)
                assert pool.pending == 2
                waiting[0].cancel()
                with pytest.raises(asyncio.CancelledError): await waiting[0]
                assert pool.pending == 2
                rejected = await client.get(base)
                assert rejected.status_code == 429 and rejected.json()['retryable']
                assert calls == [0, 1]
                assert pool is not app.state.fixture_start_pool and pool is not app.state.fixture_stop_pool
                stopped = await client.post(path, headers={**headers,'Idempotency-Key':'capacity-stop'},
                    json={**body,'action':'STOP_FIXED_SCOPE','expected_state_version':owner.store.version()})
                assert stopped.status_code == 202, stopped.text
                assert owner.pool.snapshot()['occupied'] == 0 and pool.pending == 2
                version = owner.store.version()
                closing = asyncio.create_task(lifespan.__aexit__(None, None, None))
                for _ in range(200):
                    if pool.closed: break
                    await asyncio.sleep(.01)
                assert pool.closed and not closing.done() and pool.pending == 2
                assert (await client.get(base)).status_code == 503
                release.set()
                response = await waiting[1]
                assert response.status_code == 200, response.text
                await closing
                assert pool.pending == 0 and owner.store.version() == version
        finally:
            release.set()
            await asyncio.gather(*waiting, return_exceptions=True)
            if closing is None: await lifespan.__aexit__(None, None, None)
            else: await closing
    asyncio.run(scenario())
