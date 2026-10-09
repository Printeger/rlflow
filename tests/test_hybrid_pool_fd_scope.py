"""Native Pool witness ignores foreign inodes, never ambiguous/old targets."""
import os
import sqlite3
import threading

import pytest

from rlflow import hybrid_host_pool as module
from rlflow.store import Conflict
from tests.test_hybrid_host_pool import pool


def test_foreign_actual_sqlite_wal_thread_during_pool_connect_is_not_a_candidate(pool, tmp_path, monkeypatch):
    owner, members = pool
    start, opened, close = threading.Event(), threading.Event(), threading.Event()
    failures = []
    def foreign():
        try:
            assert start.wait(5)
            with sqlite3.connect(tmp_path/'foreign.sqlite') as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE foreign_data(value)'); db.commit()
                opened.set(); assert close.wait(10)
        except BaseException as error: failures.append(error); opened.set()
    thread = threading.Thread(target=foreign); thread.start()
    original = module._native_sql_fd; injected = []
    def verify(db, before, expected):
        if not injected:
            injected.append(True); start.set(); assert opened.wait(5); assert not failures
            # Actual db/WAL/SHM adds foreign RW descriptors after the census.
            added = [pair for fd,pair in module._rw_descriptors().items() if before.get(fd)!=pair]
            assert tuple(expected) in added and any(pair!=tuple(expected) for pair in added)
        return original(db, before, expected)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, '_native_sql_fd', verify)
            assert owner.snapshot()['version'] == 2
            claim = owner.claim(members[0], expected_version=2, request_key='foreign_fd')
            assert owner.snapshot()['occupied'] == 1 and owner.check(claim)['state'] == 'CLAIM'
    finally:
        close.set(); start.set(); thread.join(10)
    assert not thread.is_alive() and not failures


@pytest.mark.parametrize('case', ['zero', 'two', 'old'])
def test_zero_multiple_or_preexisting_target_fd_never_becomes_native_capability(tmp_path, case):
    path = tmp_path/'native_target'; descriptors=[]
    fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_CLOEXEC, 0o600); descriptors.append(fd)
    expected = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
    try:
        before = module._rw_descriptors()
        if case != 'old':
            os.close(fd); descriptors.clear(); before = module._rw_descriptors()
        if case == 'two':
            descriptors.extend(os.open(path, os.O_RDWR|os.O_CLOEXEC) for _ in range(2))
        with pytest.raises(Conflict, match='native pool SQLite'):
            module._native_sql_fd(None, before, expected)
    finally:
        for descriptor in descriptors: os.close(descriptor)


def test_wrong_sqlite_connection_with_foreign_rw_noise_still_has_no_target(tmp_path):
    expected_path=tmp_path/'expected'; fd=os.open(expected_path,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_CLOEXEC,0o600)
    expected=(os.fstat(fd).st_dev,os.fstat(fd).st_ino);os.close(fd)
    before=module._rw_descriptors()
    with sqlite3.connect(tmp_path/'wrong.sqlite') as db:
        with pytest.raises(Conflict, match='native pool SQLite'):
            module._native_sql_fd(db,before,expected)
        assert db.execute("SELECT name FROM sqlite_master").fetchall()==[]
