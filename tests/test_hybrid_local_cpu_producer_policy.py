"""Pure manager producer-policy rejection; not real admission evidence."""
import pytest
from types import SimpleNamespace
from rlflow.hybrid_local_cpu_manager import OriginalServiceManager
from rlflow.store import Conflict


@pytest.mark.parametrize('bad',['Restart','NRestarts','RestartForceExitStatus','ExecCondition','ExecStartPre','ExecStartPost',
    'ExecReload','ExecStop','ExecStopPost','OnFailure','OnSuccess','Triggers','TriggeredBy'])
def test_closed_producer_policy_rejects_each_extra_route(monkeypatch,bad):
    manager=object.__new__(OriginalServiceManager);manager.unit_path='/original'
    manager.closed=False;manager.stopped_raw=None
    monkeypatch.setattr(manager,'_actual',lambda:None)
    monkeypatch.setattr(manager,'_check_socket',lambda:None)
    def prop(name,*args):
        if name=='Restart':return 'always' if bad==name else 'no'
        return 1 if bad==name else 0
    def array(name,*args):
        if name==bad:raise Conflict('additional producer '+name)
    monkeypatch.setattr(manager,'_property',prop)
    monkeypatch.setattr(manager,'_empty_property',array)
    monkeypatch.setattr(manager,'_empty_restart_force',lambda:array('RestartForceExitStatus'))
    with pytest.raises(Conflict):manager.check_closed_producers()


@pytest.mark.parametrize('changed',['admission_only','source','terminal','unit','invocation'])
def test_closed_connection_needs_same_original_post_stop_policy(monkeypatch,changed):
    manager=object.__new__(OriginalServiceManager)
    manager.unit_path='/original';manager.closed=False;manager.stopped_raw=None
    manager._closed_producer_terminal=None;manager.creator={'pid':1};manager.destination=':1.2'
    manager.unit='original.service';manager.bound={'invocation_id':'a'*32}
    manager.fd_identity=(3,4);manager._stop_nonce='b'*32
    manager.row={'source':SimpleNamespace(raw=b'original source')}
    monkeypatch.setattr(manager,'_actual',lambda:None)
    monkeypatch.setattr(manager,'_check_socket',lambda:None)
    monkeypatch.setattr(manager,'_property',lambda name,*args:'no' if name=='Restart' else 0)
    monkeypatch.setattr(manager,'_empty_property',lambda *args:None)
    monkeypatch.setattr(manager,'_empty_restart_force',lambda:None)
    manager.check_closed_producers()
    assert manager._closed_producer_terminal is None
    if changed!='admission_only':
        manager.stopped_raw=b'original terminal'
        manager.check_closed_producers()
        assert manager._closed_producer_terminal is not None
    manager.closed=True
    if changed!='admission_only':manager.check_closed_producers()
    if changed=='source':manager.row['source'].raw=b'foreign source'
    elif changed=='terminal':manager.stopped_raw=b'foreign terminal'
    elif changed=='unit':manager.unit='foreign.service'
    elif changed=='invocation':manager.bound['invocation_id']='c'*32
    with pytest.raises(Conflict,match='terminal producer policy UNKNOWN'):manager.check_closed_producers()


@pytest.mark.parametrize('fault',['exit_code','signal','structure','array','extra_field','io'])
def test_typed_restart_force_rejects_nonempty_or_malformed(monkeypatch,fault):
    manager=object.__new__(OriginalServiceManager)
    manager.bus=None;manager.destination=':1.2';manager.unit_path='/original'
    monkeypatch.setattr(manager,'_check_socket',lambda:None)
    calls=[];ends=iter([0,1,1] if fault=='exit_code' else [1,0,1] if fault=='signal' else [1,1,0] if fault=='extra_field' else [1,1,1])
    def get(*args):
        assert args[-1]==b'(aiai)'
        return -5 if fault=='io' else 1
    def enter(reply,kind,signature):
        calls.append((kind,signature))
        return 0 if fault=='structure' and kind==b'r' or fault=='array' and kind==b'a' else 1
    manager.lib=SimpleNamespace(sd_bus_get_property=get,sd_bus_message_enter_container=enter,
        sd_bus_message_at_end=lambda *args:next(ends),sd_bus_message_exit_container=lambda *args:1)
    with pytest.raises((Conflict,OSError)):manager._empty_restart_force()
