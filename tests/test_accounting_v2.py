import json
from pathlib import Path
import pytest
from rlflow import accounting,engine
from rlflow.store import canonical,atomic,Conflict
from test_engine import harness,deliver,result_for


@pytest.mark.parametrize('events,launched,expected',[
    ([],False,'NOT_STARTED'),([],True,'UNKNOWN'),
    ([{'type':'turn.started'}],True,'UNKNOWN'),
    ([{'type':'turn.failed','error':{'message':'transport'}}],True,'UNKNOWN'),
    ([{'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':0}}],True,'USED'),
    ([{'type':'item.completed','item':{'type':'agent_message','text':'generated'}},{'type':'turn.failed'}],True,'USED')])
def test_usage_evidence_not_process_existence(tmp_path,events,launched,expected):
    (tmp_path/'events.jsonl').write_bytes(b''.join(canonical(e)+b'\n' for e in events))
    assert accounting.observe(tmp_path,launched)['state']==expected


@pytest.mark.parametrize('outcome,used,reserved',[('NOT_STARTED',0,0),('USED',1,0),('UNKNOWN',0,1)])
def test_settlement_conservation_and_idempotency(harness,outcome,used,reserved):
    h=harness;sid=engine.dispatch_one(h.store);se=h.store.replay()['sessions'][sid];d=Path(se['directory'])
    atomic(d/'result.json',canonical(result_for(h,sid)))
    atomic(d/'receipt.json',canonical({'session_id':sid,'elapsed_seconds':1,'exit_code':7,'model_usage':{'state':outcome}}))
    engine.accept_result(h.store,sid);s=h.store.replay();st=s['stages']['CPU']
    assert st['used_calls']==used and st['reserved_calls']==reserved
    assert st['reserved_seconds']==reserved*5
    assert st['infrastructure_seconds']==1
    engine.accept_result(h.store,sid)
    assert h.store.rebuild()==s


def test_historical_correction_is_append_only_and_does_not_unhold(harness):
    h=harness;sid=engine.dispatch_one(h.store);se=h.store.replay()['sessions'][sid];d=Path(se['directory'])
    (d/'request.json').unlink()
    atomic(d/'validation.json',canonical({'accounting':'role call consumed; worker not launched; wall reservation released'}))
    def legacy(s):
        se=s['sessions'][sid];se.pop('accounting_version');se.update(status='REJECTED',prelaunch_failure=True,identity=None)
        st=s['stages']['CPU'];st.update(status='HOLD',used_calls=1,reserved_calls=0,reserved_seconds=0)
        st['compute']['used']['sol']=1;st['compute']['reserved_calls']['sol']=0;st['compute']['reserved_seconds']['sol']=0
    h.store.transact('FIXTURE_LEGACY','legacy',legacy)
    with h.store.connect() as db:before=[dict(r) for r in db.execute('select * from events')]
    s=accounting.correct_prelaunch(h.store,sid)
    assert s['stages']['CPU']['status']=='HOLD' and s['stages']['CPU']['used_calls']==0
    assert accounting.correct_prelaunch(h.store,sid)==s
    with h.store.connect() as db:after=[dict(r) for r in db.execute('select * from events')]
    assert after[:-1]==before
