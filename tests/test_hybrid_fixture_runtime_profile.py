"""Discovery is read-only, scoped, explicitly opt-in and not an execution grant."""
from fastapi.testclient import TestClient
from tests.test_hybrid_fixture_runtime import runtime, native_setup
from tests.test_hybrid_fixture_runtime_control import setup, ORIGIN


def test_profile_auth_closed_query_no_write_and_dead_owner_history(runtime, monkeypatch):
    owner, lease, service, app, token, _, _, _ = setup(runtime)
    path = '/api/v1/projects/' + service.project_id + '/fixture-runtime-profile'
    before = owner.store.version()
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(path).status_code == 401
        client.cookies.set('rlflow_session', token)
        with monkeypatch.context() as patch:
            patch.setattr(owner, 'poll', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('GET cannot poll')))
            response = client.get(path)
        assert response.status_code == 200
        assert response.json()['original_owner_available'] is True
        assert response.json()['execution_enabled'] is False
        assert owner.store.version() == before and not owner._issued(lease)['spawn_entered']
        assert client.get(path+'?execute=true').status_code == 400
        owner.shutdown()
        historical = client.get(path)
        assert historical.status_code == 200
        assert historical.json()['original_owner_available'] is False
        assert historical.json()['native_execution_enabled'] is False
