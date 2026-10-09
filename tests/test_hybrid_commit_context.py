"""Internal held-COMMIT contexts and post-success callback, no runtime grant."""
from contextlib import contextmanager

import pytest

from rlflow.store import Conflict
from tests.test_hybrid_controller_service import owned,acquire


def test_internal_context_covers_actual_commit_and_post_commit(owned):
    service,_,_=owned;token=acquire(service)['token'];sequence=[];held=[False]
    @contextmanager
    def context():
        assert service._token_active is not None
        sequence.append('enter');held[0]=True
        try:yield
        finally:sequence.append('exit');held[0]=False
    def before():
        assert held[0] and connection[0].in_transaction;sequence.append('before')
    def after():
        assert held[0] and not connection[0].in_transaction;sequence.append('after')
    connection=[]
    with service.token_transaction(token,_commit_context=context,_before_commit=before,
                                   _after_commit=after) as (db,_,__):
        connection.append(db);assert held[0];sequence.append('body')
    assert sequence==['enter','body','before','after','exit'] and service._token_active is None


@pytest.mark.parametrize('fault',['body','context_enter','after_commit'])
def test_context_fault_paths_clear_controller_active_without_second_callback(owned,fault):
    service,_,_=owned;token=acquire(service)['token'];sequence=[]
    @contextmanager
    def context():
        if fault=='context_enter':raise Conflict('context_enter')
        try:yield
        finally:sequence.append('exit')
    def after():
        sequence.append('after_commit')
        if fault=='after_commit':raise Conflict('after_commit')
    with pytest.raises(Conflict,match=fault):
        with service.token_transaction(token,_commit_context=context,_after_commit=after) as (_,__,___):
            if fault=='body':raise Conflict('body')
    assert sequence==({'body':['exit'],'context_enter':[],'after_commit':['after_commit','exit']}[fault])
    assert service._token_active is None
    with service.token_transaction(token):pass


@pytest.mark.parametrize('committed',[False,True])
def test_commit_exception_never_calls_success_hook_even_when_sql_commit_happened(owned,monkeypatch,committed):
    service,_,_=owned;token=acquire(service)['token'];original=service.store.connect;called=[]
    class Connection:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def commit(self):
            if committed:self.db.commit()
            raise Conflict('uncertain commit return')
        def __enter__(self):self.db.__enter__();return self
        def __exit__(self,*args):return self.db.__exit__(*args)
    monkeypatch.setattr(service.store,'connect',lambda:Connection(original()))
    with pytest.raises(Conflict,match='uncertain commit'):
        with service.token_transaction(token,_after_commit=lambda:called.append('success')) as (db,_,__):
            db.execute('CREATE TABLE disposable_commit_probe(value INTEGER)')
            db.execute('INSERT INTO disposable_commit_probe VALUES(1)')
    assert not called and service._token_active is None
    monkeypatch.undo()
    with service.store.read_connection() as db:
        present=db.execute("SELECT 1 FROM sqlite_master WHERE name='disposable_commit_probe'").fetchone()
        assert bool(present)==committed
        if present:assert db.execute('SELECT value FROM disposable_commit_probe').fetchone()[0]==1


@pytest.mark.parametrize('fault',['body','before_commit','final_sample','after_final_sample','after_commit'])
def test_lock_context_cannot_suppress_failure_into_outer_sqlite_commit(owned,monkeypatch,fault):
    service,_,_=owned;token=acquire(service)['token'];called=[]
    class SuppressingContext:
        def __enter__(self):return self
        def __exit__(self,*args):called.append('exit');return True
    def failed():raise Conflict('failed '+fault)
    def final_failure(*args):failed()
    def after():
        called.append('success')
        if fault=='after_commit':failed()
    if fault=='final_sample':monkeypatch.setattr(service,'_final_token_freshness',final_failure)
    with pytest.raises(Conflict,match='failed '+fault):
        with service.token_transaction(token,_commit_context=SuppressingContext,
                _before_commit=failed if fault=='before_commit' else None,
                _after_final_sample=final_failure if fault=='after_final_sample' else None,
                _after_commit=after) as (db,_,__):
            db.execute('CREATE TABLE forbidden_suppressed_commit(value INTEGER)')
            if fault=='body':failed()
    assert called==(['success','exit'] if fault=='after_commit' else ['exit']) and service._token_active is None
    with service.store.read_connection() as db:
        present=db.execute("SELECT 1 FROM sqlite_master WHERE name='forbidden_suppressed_commit'").fetchone()
        assert bool(present)==(fault=='after_commit')
