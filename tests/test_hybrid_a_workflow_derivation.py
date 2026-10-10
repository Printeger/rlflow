"""Original first Engineer registration and replay; no actual model execution."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rlflow.hybrid_budget import zero
from rlflow.hybrid_goals import digest
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.hybrid_native_model_runtime import NativeModelOwner
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Conflict
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_working_plan_service import plans as plan_fixture
from tests.test_hybrid_a_workflow_profile import spec, workflow
from tests.test_hybrid_native_model_runtime import actual_binary_hash

FILES={'module/source.py':'def parse_entries(text):\n    return text.splitlines()\n'}


def workflow_bound(config):
    value=spec();value['candidate_paths']=['module/source.py']
    value['model_binary_sha256']=actual_binary_hash()
    import rlflow.hybrid_native_model_gate as gate
    value['model_gate_sha256']='sha256:'+hashlib.sha256(Path(gate.__file__).read_bytes()).hexdigest()
    registry,p=workflow(value)
    # Keep native fixture's protected execution profile for original preparation.
    row=json.loads(registry._raw);row['runtime_profile']=config['runtime_profile']
    registry=Registry(row);p['registry_bindings']=registry.bindings
    p['scope']['writable_paths']=['module/']
    return registry,p


@pytest.fixture
def original(tmp_path,native_setup,monkeypatch):
    tmp_path.chmod(0o700);pool=HostPoolOwner.create_fixture(tmp_path)
    options=dict(bound=workflow_bound,source=FILES['module/source.py'],
        amount={**zero(),'model_sessions':1,'model_input_tokens':50000,
                'model_output_tokens':4000,'wall_seconds':310})
    fixture=plan_fixture.__wrapped__(pool.projects_root,native_setup,SimpleNamespace(param=options),monkeypatch)
    plans,token,observation,*_=next(fixture);owner=None
    try:
        member=pool.register_project(plans.installation,plans.material,expected_version=0)
        claim=pool.claim(member,expected_version=1,request_key='workflow_claim',seconds=60)
        owner=NativeModelOwner(pool,member,plans)
        bundle=plans.prepare_plan(token,observation,'workflow_plan')
        plans.persist_intent(bundle,token,observation,expected_version=plans.store.version())
        plans.publish(bundle,token,observation,expected_version=plans.store.version())
        yield owner,bundle,token,observation,claim
    finally:
        if owner is not None and owner._live:
            try:owner.shutdown()
            finally:
                if owner._live:owner.shutdown_safety()
        fixture.close()
        if pool._live:pool.shutdown()


def test_original_workflow_first_engineer_register_stop_and_cold_replay(original,monkeypatch):
    owner,bundle,token,obs,claim=original
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:pytest.fail('no model process authorized'))
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    with pytest.raises(Conflict):owner.issue_workflow_engineer_grant(bundle,token,obs,
        files={'module/source.py':'forged original source'})
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    frozen=json.loads(grant.raw)
    assert frozen['workflow']['stage']=='FIRST_ENGINEER'
    assert frozen['workflow']['files']==FILES
    lease=owner.register(bundle,token,obs,claim,request_key='workflow_first',
        scenario='native_model',native_model_grant=grant)
    attempt=owner._issued(lease);row=owner.sources._issued(attempt['source'])
    assert json.loads(owner._native_model_grants[id(grant)]['packet_raw'])['files']==FILES
    with pytest.raises(PermissionError):owner.start(lease)
    # Native V1 issuer cannot borrow the new workflow approval as a V1 packet.
    with pytest.raises((Conflict,ProtocolError)):
        owner.issue_native_model_grant(bundle,token,obs,
            packet=json.loads(owner._native_model_grants[id(grant)]['packet_raw']),
            output_schema=json.loads(owner._native_model_grants[id(grant)]['schema_raw']))
    owner.stop_to_terminal(lease)
    assert owner._current(attempt)['status']=='SETTLED' and owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())
    owner.store.snapshot()
    assert owner.store.recover()==owner.store.audit()==owner.store.replay()
    from rlflow.hybrid_fixture_runtime_ledger import validate_original_links
    terminal=attempt['entries']['FIXTURE_SCOPE_STOPPED']
    forged=json.loads(json.dumps(terminal))
    forged['request']['fixture_runtime']['origin']['native_model']['workflow']['intent']['hash']=digest('changed parent')
    with pytest.raises(Conflict):validate_original_links(forged,lambda s,k:owner.store.get(s,k))
