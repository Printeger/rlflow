import pytest

from rlflow.web_auth import AuthStore, Credential, Principal


def human(projects=frozenset({"project_one"}), roles=frozenset({"viewer"})):
    return Principal("local", "human", roles, projects)


def test_credentials_hash_and_project_scope():
    phrase = "synthetic local passphrase only"
    credential = Credential.create(human(), phrase)
    assert phrase not in repr(credential)
    auth = AuthStore([credential])
    assert auth.login("missing", phrase) is None
    assert auth.login("local", "wrong") is None
    token, access = auth.login("local", phrase)
    assert token not in repr(auth._sessions)
    assert access.principal.allows("project_one")
    assert not access.principal.allows("project_two")
    assert not access.principal.allows("project_one", "operator")
    assert auth.resolve(token, "bearer") is None
    assert auth.resolve(token, "session") == access
    auth.revoke(token)
    assert auth.resolve(token, "session") is None


def test_expiry_capacity_and_method_isolation():
    now = [1.0]
    auth = AuthStore(ttl=10, max_sessions=1, clock=lambda: now[0])
    token, access = auth.issue_bearer(human(), ttl=10)
    assert auth.issue_bearer(human(), ttl=10) is None
    assert auth.resolve(token, "session") is None
    now[0] = 11
    assert auth.resolve(token, "bearer") is None
    assert auth.issue_bearer(human(), ttl=10)


def test_agent_human_approval_and_bearer_privileges_are_rejected():
    with pytest.raises(ValueError):
        Principal("agent", "agent", frozenset({"approver"}), frozenset({"project_one"}))
    with pytest.raises(ValueError):
        AuthStore().issue_bearer(human(roles=frozenset({"operator"})))
    with pytest.raises(ValueError):
        AuthStore().issue_bearer(human(), ttl=301)
    with pytest.raises(ValueError):
        Credential.create(human(), "short")


def test_login_rate_limit_is_bounded_without_user_key_growth():
    auth = AuthStore()
    for i in range(100):
        assert auth.login(str(i), "bad") is None
    assert len(auth._login_times) == 10
    assert auth._sessions == {}
