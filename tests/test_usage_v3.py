import json
import pytest
from rlflow.usage import read,estimate,reconcile
from rlflow.store import Conflict,Store


def append(path,*events):
    with path.open('ab') as f:
        for event in events:f.write(json.dumps(event).encode()+b'\n')


def event(i,o=None,c=None,**extra):
    usage={'input_tokens':i}
    if o is not None:usage['output_tokens']=o
    if c is not None:usage['cached_input_tokens']=c
    return {'type':'turn.completed','usage':usage,**extra}


def test_installed_cumulative_semantics_and_incremental_reconciliation(tmp_path):
    path=tmp_path/'events.jsonl';append(path,{'type':'thread.started','thread_id':'t'},event(100,10,20))
    first=read(path,model='fixture');assert first['input_tokens']==100
    append(path,event(300,30,60))
    second=read(path,first,model='fixture');assert second['input_tokens']==300
    assert second['output_tokens']==30 and second['cached_tokens']==60
    assert read(path,second,model='fixture')==second
    append(path,{'type':'thread.started','thread_id':'new'},event(20,2,5))
    assert read(path,second,model='fixture')['input_tokens']==320


def test_partial_truncated_late_unknown_and_failure(tmp_path):
    path=tmp_path/'events.jsonl';append(path,event(100))
    partial=read(path);assert partial['output_tokens'] is None and not partial['complete']
    with path.open('ab') as f:f.write(b'{"type":"turn.completed","usage":{"input_tokens":200')
    held=read(path,partial);assert held['offset']==partial['offset']
    with path.open('ab') as f:f.write(b',"output_tokens":10,"cached_input_tokens":20}}\n')
    late=read(path,held);assert late['input_tokens']==200 and late['output_tokens']==10
    append(path,{'type':'item.completed','item':{'type':'agent_message'}},{'type':'turn.failed'})
    failed=read(path,late);assert failed['generated'] and not failed['complete']
    path.write_text('')
    with pytest.raises(Conflict,match='truncated'):read(path,failed)


def test_per_turn_duplicates_and_price_estimate(tmp_path):
    path=tmp_path/'events.jsonl';append(path,event(100,10,20,turn_id='a'),event(100,10,20,turn_id='a'),event(100,10,20,turn_id='b'))
    usage=read(path,model='fixture',semantics='per_turn');assert usage['input_tokens']==200
    price={'model':'fixture','date':'2026-09-16','currency':'USD','version':'test-only','input_per_million':2,'cached_per_million':1,'output_per_million':5}
    result=estimate(usage,price)
    assert result['estimated_cost']=='0.00046' and result['actual_cost_status']=='UNKNOWN'
    assert estimate(usage,{**price,'model':'unknown'})['estimated_cost'] is None


def test_late_usage_appends_once(tmp_path):
    store=Store(tmp_path/'state');directory=tmp_path/'role';directory.mkdir()
    # Usage reconciliation can also be used for historical records lacking token fields.
    session={'id':'s','directory':str(directory),'compute':{'model':'fixture'}}
    # The session fixture is injected at SQL projection level to keep this test independent of role schema.
    with store.connect() as db:
        db.execute("INSERT INTO projection(section,object_key,value,version) VALUES('sessions','s',?,0)",(json.dumps(session),))
    append(directory/'events.jsonl',event(100,10,20))
    reconcile(store,'s');version=store.version();reconcile(store,'s');assert store.version()==version
    append(directory/'events.jsonl',event(200,20,40));reconcile(store,'s')
    assert store.version()==version+1 and store.get('usage','s')['input_tokens']==200


def test_strict_money_cap_rejected_and_unknown_not_zero():
    from rlflow.usage import validate_policy,admit
    policy={'token_limit':1000,'cost_limit':None,'currency':'USD','per_call_estimate':{'input_tokens':100,'output_tokens':10,'cached_tokens':20},'price_table':[],'strict_cost_cap':False}
    state={'sessions':{'s':{'stage_id':'stage','model_accounting':'UNKNOWN'}},'usage':{}}
    with pytest.raises(Conflict,match='incomplete'):admit(state,{'id':'stage','usage_policy':policy},'unknown-model')
    with pytest.raises(Conflict,match='strict'):validate_policy({**policy,'strict_cost_cap':True})
