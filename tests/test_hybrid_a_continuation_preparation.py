"""Preparation bookkeeping harness; not runtime/approval/Source qualification."""
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from rlflow.hybrid_a_continuation_runtime import prepare_plan
from rlflow.store import Conflict,canonical


@pytest.mark.parametrize('fault',['none','lost_reserve','stop_after_reserve'])
def test_original_reserve_result_is_retained_and_failure_cannot_remint(monkeypatch,fault):
    import rlflow.hybrid_a_continuation_runtime as module
    actions=[];token=object();bundle=object();entry={'ORIGINAL_ENTRY_HARNESS':True}
    accepted={'request':{'project_id':'project','data_mode':'live','store_epoch':'epoch','goal_ref':'goal'}}
    value={'acceptance':{'key':'accepted','hash':'sha256:'+'a'*64},
        'packet':{'objective':'Explicit next task'},'spec':{'model_input_tokens':50000,'model_output_tokens':4000,'seconds':300}}
    @contextmanager
    def connection():yield SimpleNamespace(execute=lambda *args:None)
    obs=SimpleNamespace(raw=canonical({'workspace_id':'workspace'}))
    owner=SimpleNamespace(_actual=lambda:None,_safety_freeze=False,
        _workflow_cpu_sequence_lock=threading.Lock(),_workflow_cpu_admission_lock=threading.RLock(),
        _continuation_plan_sequence=None,
        _continuation_parent=(None,None,None,(None,None,None,None,canonical({'acceptance':accepted}))),
        controller=SimpleNamespace(_issued=lambda t:None,check_token=lambda t:None),
        store=SimpleNamespace(read_connection=connection,version=lambda:10))
    def reserve(request,t):
        actions.append(('reserve',request))
        assert request['store_epoch']=='epoch' and request['amount']['wall_seconds']==310
        if fault=='lost_reserve':raise OSError('TEST lost original reserve response')
        if fault=='stop_after_reserve':owner._safety_freeze=True
        return {'entry':entry,'duplicate':False}
    owner.budget=SimpleNamespace(_load=lambda *args:{},record=reserve)
    owner.workspace=SimpleNamespace(
        preparation=SimpleNamespace(prepare=lambda request:actions.append(('prepare',request))),
        stage=lambda *args,**kwargs:actions.append(('stage',None)) or obs,
        record=lambda *args:actions.append(('acquire',None)))
    owner.plans=SimpleNamespace(prepare_plan=lambda *args:bundle,
        persist_intent=lambda *args,**kwargs:None,publish=lambda *args,**kwargs:None)
    monkeypatch.setattr(module,'admission',lambda *args,**kwargs:(value,accepted,{}))
    if fault=='none':
        assert prepare_plan(owner,token)==(bundle,obs)
        assert owner._continuation_plan_sequence['reserved'] is entry
        assert owner._continuation_plan_sequence['phase']=='READY'
    else:
        with pytest.raises((OSError,Conflict)):prepare_plan(owner,token)
        assert [action for action,_ in actions]==['prepare','reserve']
        if fault=='lost_reserve':assert 'reserved' not in owner._continuation_plan_sequence
        else:assert owner._continuation_plan_sequence['reserved'] is entry
    count=len(actions)
    with pytest.raises(Conflict,match='no remint'):prepare_plan(owner,token)
    assert len(actions)==count
