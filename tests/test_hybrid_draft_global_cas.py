from copy import deepcopy
import json
from pathlib import Path

import pytest

from rlflow.hybrid_goals import propose, SECTIONS, command_key, digest
from rlflow.hybrid_protocol import ProtocolError
from rlflow.observation import enable
from rlflow.store import Store, Conflict
from rlflow.web_auth import Principal
from rlflow.contracts import ContractError


def setup(tmp_path):
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    proposal=json.loads(Path('docs/rlflow_hybrid_spec_v1/examples/goal.fixture.json').read_text())
    args={'principal':Principal('operator','human',{'operator'},{'project_fixture'}),
          'project_id':'project_fixture','data_mode':'fixture','idempotency_key':'first','expected_revision':0}
    return store,proposal,args


def test_global_cas_is_in_actual_transaction_and_original_retry(tmp_path):
    store,p,args=setup(tmp_path)
    first=propose(store,p,**args,expected_state_version=0)
    receipt=store.objects(SECTIONS[2])[0][1]
    assert receipt['request']['expected_state_version']==0 and receipt['request_hash']==digest(receipt['request'])
    assert command_key(receipt['request'])==store.objects(SECTIONS[2])[0][0]
    store.transact_objects('USAGE_OBSERVED','other',[('usage','other')],lambda s:s.setdefault('usage',{}).update(other={}))
    assert propose(store,p,**args,expected_state_version=0)=={**first,'duplicate':True}
    before=store.audit();p2=deepcopy(p);p2['contract_version']=2
    with pytest.raises(Conflict,match='stale'):
        propose(store,p2,**{**args,'idempotency_key':'second','expected_revision':1},expected_state_version=1)
    assert store.audit()==before
    second=propose(store,p2,**{**args,'idempotency_key':'second','expected_revision':1},expected_state_version=2)
    assert second['accepted_state_version']==3
    store.snapshot();assert store.recover()==store.audit()==store.replay()


def test_global_cas_payload_changes_do_not_reuse_original_receipt(tmp_path):
    store,p,args=setup(tmp_path);propose(store,p,**args,expected_state_version=0);before=store.audit()
    for version in (None,1):
        with pytest.raises(Conflict,match='idempotency'):propose(store,p,**args,expected_state_version=version)
    assert store.audit()==before


def test_legacy_request_remains_without_added_field(tmp_path):
    store,p,args=setup(tmp_path);propose(store,p,**args)
    receipt=store.objects(SECTIONS[2])[0][1]
    assert 'expected_state_version' not in receipt['request']
    before=deepcopy(receipt);store.snapshot();store.recover()
    assert store.objects(SECTIONS[2])[0][1]==before


@pytest.mark.parametrize('version',[True,-1,2**63,1.0,'0'])
def test_invalid_global_cas_rejected_without_effect(tmp_path,version):
    store,p,args=setup(tmp_path);before=store.audit()
    with pytest.raises(ProtocolError):propose(store,p,**args,expected_state_version=version)
    assert store.audit()==before


def test_core_gate_still_rejects_when_caller_omits_store_cas(tmp_path,monkeypatch):
    store,p,args=setup(tmp_path);before=store.audit();original=store.transact_objects
    def bypass_caller_cas(*a,**kw):
        kw['expected']=None
        return original(*a,**kw)
    monkeypatch.setattr(store,'transact_objects',bypass_caller_cas)
    with pytest.raises(ContractError,match='global version'):
        propose(store,p,**args,expected_state_version=50)
    assert store.audit()==before
