"""Pure original reply binding guards; not a live manager or execution grant."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from rlflow.hybrid_local_cpu_manager import OriginalServiceManager,_OriginalStopReply,_stop_replies
from rlflow.store import Conflict,canonical


@pytest.fixture
def reply_guard(monkeypatch):
    # Remove kernel/RPC prerequisites ONLY for deterministic context tests.
    # Real original owner/JobRemoved/STOP/FREE qualification is in runtime tests.
    manager=object.__new__(OriginalServiceManager)
    manager.creator={'pid':1};manager.destination=':1.2';manager.unit='original.service'
    manager.bound={'pid':2,'invocation_id':'a'*32};manager.fd_identity=(3,4)
    manager._stop_nonce='b'*32;manager.stop_entered=True;manager._stop_wire_entered=True
    manager.row={'manager':manager,'source':SimpleNamespace(raw=b'original source')}
    monkeypatch.setattr(manager,'_check_socket',lambda:None)
    job='/org/freedesktop/systemd1/job/123'
    receipt=_OriginalStopReply(manager,canonical(manager._stop_reply_context(job)),job)
    _stop_replies[id(manager)]=receipt
    try:yield manager,receipt
    finally:_stop_replies.pop(id(manager),None)


@pytest.mark.parametrize('field',['creator','destination','unit','bound','fd_identity','_stop_nonce','source','owner','context','job','missing'])
def test_stop_reply_requires_same_original_context(reply_guard,field):
    manager,receipt=reply_guard
    assert manager._original_stop_job()==receipt.job
    if field=='creator':manager.creator={'pid':99}
    elif field=='destination':manager.destination=':1.99'
    elif field=='unit':manager.unit='foreign.service'
    elif field=='bound':manager.bound={'pid':99,'invocation_id':'c'*32}
    elif field=='fd_identity':manager.fd_identity=(99,100)
    elif field=='_stop_nonce':manager._stop_nonce='c'*32
    elif field=='source':manager.row['source']=SimpleNamespace(raw=b'foreign source')
    elif field=='owner':_stop_replies[id(manager)]=replace(receipt,owner=object())
    elif field=='context':_stop_replies[id(manager)]=replace(receipt,context=b'foreign')
    elif field=='job':object.__setattr__(receipt,'job','/org/freedesktop/systemd1/job/999')
    else:_stop_replies.pop(id(manager))
    with pytest.raises(Conflict):manager._original_stop_job()


def test_fatal_exception_not_swallowed_and_no_second_stop_call(reply_guard,monkeypatch):
    manager,_=reply_guard;_stop_replies.pop(id(manager));calls=[]
    manager.stopped_raw=None;manager.stop_job=None;manager.stop_entered=False
    monkeypatch.setattr(manager,'_actual',lambda:None)
    monkeypatch.setattr(manager,'snapshot',lambda:{})
    def fatal(*args,**kwargs):calls.append(args[0]);raise KeyboardInterrupt('fatal caller failure')
    monkeypatch.setattr(manager,'_call',fatal)
    with pytest.raises(KeyboardInterrupt):manager.stop()
    assert manager.stop_entered and manager.stop_job is None
    with pytest.raises(Conflict,match='wire reply UNKNOWN'):manager.stop()
    assert calls==['StopUnit']


def test_changed_job_cannot_resume_stop_or_publish_terminal(reply_guard,monkeypatch):
    manager,receipt=reply_guard;calls=[]
    manager.stop_job=None;manager.stopped_raw=None
    monkeypatch.setattr(manager,'_actual',lambda:None)
    monkeypatch.setattr(manager,'snapshot',lambda:{})
    monkeypatch.setattr(manager,'_call',lambda *args,**kwargs:calls.append(args[0]))
    object.__setattr__(receipt,'job','/org/freedesktop/systemd1/job/999')
    with pytest.raises(Conflict,match='context differs'):manager.stop()
    assert calls==[] and manager.stop_job is None and manager.stopped_raw is None
