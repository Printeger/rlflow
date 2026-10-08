from concurrent.futures import ThreadPoolExecutor
from copy import copy

import pytest

from rlflow.web_auth import _ApprovalSessionGuard
from tests.test_approval_session_guard import auth_fixture


def test_issuer_only_accepts_actual_active_guard_not_equivalent_copies():
    auth, token, access, _ = auth_fixture()
    with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as guard:
        assert auth.check_approval_guard(guard, project_id='project_fixture') == access
        for fake in (copy(guard), _ApprovalSessionGuard(guard._check), _ApprovalSessionGuard(lambda: access),
                     access, access.principal, None):
            with pytest.raises(PermissionError):auth.check_approval_guard(fake, project_id='project_fixture')
    assert not auth._approval_guards
    with pytest.raises(PermissionError):auth.check_approval_guard(guard, project_id='project_fixture')


def test_guard_from_different_auth_owner_or_project_is_rejected():
    auth, token, access, _ = auth_fixture(); other, _, _, _ = auth_fixture()
    with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as guard:
        with pytest.raises(PermissionError):other.check_approval_guard(guard, project_id='project_fixture')
        with pytest.raises(PermissionError):auth.check_approval_guard(guard, project_id='other_project')
        assert auth.check_approval_guard(guard, project_id='project_fixture') == access


def test_cross_thread_cannot_authenticate_with_issued_guard():
    auth, token, access, _ = auth_fixture()
    with auth.approval_guard(token, project_id='project_fixture', csrf=access.csrf) as guard:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(auth.check_approval_guard, guard, project_id='project_fixture')
            with pytest.raises(PermissionError):future.result(timeout=2)


@pytest.mark.parametrize('failure', ['entry', 'body', 'expiry'])
def test_issued_guard_membership_is_cleared_on_every_exception(failure):
    auth, token, access, now = auth_fixture()
    with pytest.raises((PermissionError, RuntimeError)):
        with auth.approval_guard(token, project_id='project_fixture', csrf='not_the_real_csrf_token_12345' if failure == 'entry' else access.csrf) as guard:
            assert len(auth._approval_guards) == 1
            if failure == 'body':raise RuntimeError('fixture controlled failure')
            now[0] = 11.0
            auth.check_approval_guard(guard, project_id='project_fixture')
    assert not auth._approval_guards
    assert auth.resolve(token, 'session') is None if failure == 'expiry' else auth.resolve(token, 'session') == access


def test_oversize_ascii_token_is_rejected_before_any_hash(monkeypatch):
    auth, _, access, _ = auth_fixture()
    def forbidden(token):raise AssertionError('oversize token was hashed')
    monkeypatch.setattr(auth,'_key',forbidden)
    with pytest.raises(PermissionError):
        with auth.approval_guard('x'*10000,project_id='project_fixture',csrf=access.csrf):pass
    assert not auth._approval_guards
