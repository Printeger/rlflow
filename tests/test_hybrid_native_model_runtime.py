"""Original local generating registration; zero real model/auth/GPU access."""
import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from rlflow.hybrid_native_model_runtime import NativeModelOwner, NativeModelGrant, bind_packet
from rlflow.hybrid_native_model_profile import PROFILE, registration, KIND
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_goals import digest
from rlflow.hybrid_budget import zero
from rlflow.store import Conflict
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_working_plan_service import plans as plan_fixture
from tests.test_hybrid_registry import bound

FILES = {'module/source.py':'def normalize(value):\n    return value\n'}
OUTPUT_SCHEMA = {'type':'object','properties':{'edits':{'type':'array'}},
                 'required':['edits'],'additionalProperties':False}
PACKET = None


def generating_bound(config):
    global PACKET
    _, proposal = bound(config)
    proposal.update(goal_kind='engineering', objective='Implement the approved normalization behavior')
    PACKET = dict(role='Engineer',files=FILES,objective=proposal['objective'],conditions=proposal['global_conditions'])
    import rlflow.hybrid_native_model_runtime as runtime_module
    gate_hash = 'sha256:'+hashlib.sha256(Path(runtime_module.__file__).read_bytes()).hexdigest()
    spec = dict(profile=PROFILE,role='Engineer',model='gpt-6.1-sol',effort='medium',
        account_mode='CHATGPT_CURRENT_WORKSPACE_ONLY',workspace_id='12345678-1234-1234-1234-123456789012',
        packet_sha256=digest(PACKET),output_schema_sha256=digest(OUTPUT_SCHEMA),candidate_sha256=digest(FILES),
        binary_sha256='sha256:'+'a'*64,gate_sha256=gate_hash,
        model_input_tokens=1000,model_output_tokens=100,seconds=10,
        token_enforcement='SOFT_APPROVED',network_enforcement='PARTIAL_NOT_QUALIFIED',
        model_tools=False,api_billing=False,account_switch=False,gpu_enabled=False)
    rows=registration(spec)
    config.update(tools={'native_model':rows['tool']},commands={'native_model':rows['command']},
        evaluation_rules={'native_model_rule':rows['rule']},resource_profile=rows['resources'])
    config['project_policy'].update(network_access='allowlist',allowed_hosts=['chatgpt.com'])
    registry=Registry(config)
    proposal.update(allowed_tools=['native_model'],registry_bindings=registry.bindings,
        evaluation_data=dict(mode='EXPLICIT_NONE',datasets=[],
            evaluation_rule=dict(id='native_model_rule',version_hash=digest(rows['rule']))))
    proposal['scope'].update(allowed_command_templates=['native_model'],network_access='allowlist',allowed_hosts=['chatgpt.com'])
    proposal['budget'].update(model_sessions=8,model_input_tokens=10000,model_output_tokens=1000,
                             wall_seconds=600,model_token_enforcement='soft_approved')
    return registry,proposal


@pytest.fixture
def model_runtime(tmp_path,native_setup,monkeypatch):
    tmp_path.chmod(0o700); pool=HostPoolOwner.create_fixture(tmp_path)
    options=dict(bound=generating_bound,source=FILES['module/source.py'],
        amount={**zero(),'model_sessions':1,'model_input_tokens':1000,'model_output_tokens':100,'wall_seconds':20})
    fixture=plan_fixture.__wrapped__(pool.projects_root,native_setup,SimpleNamespace(param=options),monkeypatch)
    plans,token,observation,*_=next(fixture)
    owner=None
    try:
        member=pool.register_project(plans.installation,plans.material,expected_version=0)
        claim=pool.claim(member,expected_version=1,request_key='model_claim',seconds=60)
        owner=NativeModelOwner(pool,member,plans)
        bundle=plans.prepare_plan(token,observation,'model_plan')
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


def test_original_generating_grant_registers_frozen_source_but_cannot_launch(model_runtime,monkeypatch):
    owner,bundle,token,observation,claim=model_runtime
    def forbidden(*args,**kwargs):pytest.fail('unqualified generating scope must never launch a process')
    monkeypatch.setattr('subprocess.Popen',forbidden)
    grant=owner.issue_native_model_grant(bundle,token,observation,packet=PACKET,output_schema=OUTPUT_SCHEMA)
    with pytest.raises(PermissionError):owner.register(bundle,token,observation,claim,request_key='copy',
        scenario='native_model',native_model_grant=NativeModelGrant(grant.id,grant.raw))
    lease=owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant)
    assert owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant) is lease
    attempt=owner._issued(lease);source=owner.sources._issued(attempt['source'])
    assert attempt['origin']['kind']==KIND and not attempt['spawn_entered']
    assert not json.loads(attempt['source'].raw)['execution_qualified']
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    with pytest.raises(PermissionError,match='qualification'):owner.start(lease)
    with pytest.raises(PermissionError):owner.sources.start_fixture(owner.membership,claim)
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    assert source['producer'] is None
    data = owner.sources.poll_packet_data(attempt['source'])
    assert data['offset']==0 and not data['source_authenticated'] and not data['data_complete']
    with pytest.raises(PermissionError,match='producer qualification'):
        owner.sources.poll(attempt['source'])
    with pytest.raises(PermissionError,match='no source publication'):
        owner.sources.seal(attempt['source'])
    owner.stop_to_terminal(lease)
    assert owner._current(attempt)['status']=='SETTLED'
    assert owner.pool.snapshot()['occupied']==0 and all(fd is None for fd in source['fds'].values())
    assert owner.store.audit()==owner.store.replay()


def test_original_packet_tamper_rejected_and_physical_cleanup_remains_available(model_runtime):
    owner,bundle,token,observation,claim=model_runtime
    grant=owner.issue_native_model_grant(bundle,token,observation,packet=PACKET,output_schema=OUTPUT_SCHEMA)
    lease=owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant)
    row=owner.sources._issued(owner._issued(lease)['source'])
    (row['path']/'packet.json').write_text('{}')
    with pytest.raises(Conflict,match='packet/schema changed'):owner.sources._physical(row)
    # No task or native process ever started; immutable identity-preserving
    # data corruption cannot block independently closing the original FDs.
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())


def test_packet_source_failure_latches_after_bytes_restored_and_reader_replaced(model_runtime):
    owner,bundle,token,observation,claim=model_runtime
    grant=owner.issue_native_model_grant(bundle,token,observation,packet=PACKET,output_schema=OUTPUT_SCHEMA)
    lease=owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant)
    source=owner._issued(lease)['source']; row=owner.sources._issued(source)
    path=row['path']/'packet.json'; original=path.read_bytes()
    reader=owner.sources._packet_readers[id(source)]
    path.write_bytes(b'{}')
    with pytest.raises(Conflict,match='packet/schema changed'):
        owner.sources.poll_packet_data(source)
    assert reader.failed and row['status']=='QUARANTINED'
    path.write_bytes(original)
    from rlflow.hybrid_native_packet_reader import _HeldPacketReader
    owner.sources._packet_readers[id(source)]=_HeldPacketReader(row['fds']['read'],
        role='Engineer',candidate_sha256=digest(FILES))
    with pytest.raises(Conflict,match='failed; no replacement'):
        owner.sources.poll_packet_data(source)
    # Immutable data refusal does not block independent original FD cleanup.
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())


def test_original_handoff_without_producer_proof_retains_budget_and_pool(model_runtime):
    owner,bundle,token,observation,claim=model_runtime
    grant=owner.issue_native_model_grant(bundle,token,observation,packet=PACKET,output_schema=OUTPUT_SCHEMA)
    lease=owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant)
    attempt=owner._issued(lease)
    # Original protected HANDOFF intent only, never producer creation/G/model.
    value=owner._write_phase(attempt,'HANDOFF_UNKNOWN')
    owner.pool._fixture_runtime_change(owner,lease,'FIXTURE_HANDOFF_UNKNOWN',value)
    assert owner._current(attempt)['fixture_runtime']['native_model_handoff_attempted']
    # HANDOFF alone cannot prove original no-spawn lineage. Do not weaken the
    # shared historical gate or synthesize a native producer to obtain FREE.
    with pytest.raises(Conflict,match='NO_HANDOFF lineage'):owner.stop_to_terminal(lease)
    reservation=owner._current(attempt)
    assert reservation['status']=='UNKNOWN'
    from rlflow.hybrid_budget_ledger import SECTIONS, project_key
    project=owner.store.get(SECTIONS[3],project_key(owner.workspace.project_id,'fixture'))
    assert project['reserved']==reservation['amount'] and project['unknown_exposure']==reservation['amount']
    assert project['consumed']==zero()
    assert owner.pool.snapshot()['occupied']==1
    assert attempt['producer_identity'] is None and not attempt['spawn_entered']
    assert owner.store.audit()==owner.store.replay()
    owner.shutdown_safety()
    assert not owner._live and owner.pool.snapshot()['occupied']==1


@pytest.mark.parametrize('damage',['role','candidate','task','conditions','manifest','packet_hash'])
def test_packet_binding_cannot_substitute_task_role_or_working_snapshot(damage):
    packet=dict(role='Engineer',files=FILES,objective='approved objective',conditions=[])
    binding=dict(role='Engineer',candidate_sha256=digest(FILES),packet_sha256=digest(packet))
    manifest=[dict(name=name,bytes=len(text.encode()),sha256='sha256:'+hashlib.sha256(text.encode()).hexdigest(),mode=0o600)
        for name,text in sorted(FILES.items())]
    intent=dict(plan=dict(packet=dict(role='Engineer'),working_tree=dict(files=manifest)))
    proposal=dict(objective=packet['objective'],global_conditions=[])
    assert bind_packet(packet,binding,intent,proposal)
    packet=deepcopy(packet);intent=deepcopy(intent)
    if damage=='role':intent['plan']['packet']['role']='Evaluator'
    elif damage=='candidate':binding['candidate_sha256']='sha256:'+'0'*64
    elif damage=='task':packet['objective']='another task'
    elif damage=='conditions':packet['conditions']=['caller PASS']
    elif damage=='manifest':intent['plan']['working_tree']['files'][0]['sha256']='sha256:'+'0'*64
    else:binding['packet_sha256']='sha256:'+'0'*64
    with pytest.raises(Conflict):bind_packet(packet,binding,intent,proposal)


@pytest.mark.parametrize('damage',['marker','paired_raw'])
def test_published_source_cannot_disable_or_launder_original_content_check(model_runtime,damage):
    owner,bundle,token,observation,claim=model_runtime
    grant=owner.issue_native_model_grant(bundle,token,observation,packet=PACKET,output_schema=OUTPUT_SCHEMA)
    lease=owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant)
    row=owner.sources._issued(owner._issued(lease)['source'])
    row['model_allocated']=False
    (row['path']/'packet.json').write_text('{}')
    if damage=='paired_raw':
        row['model_raw']['packet']=b'{}'
        raw=json.loads(row['source'].raw);raw['native_model']['packet_sha256']=digest({})
        from rlflow.store import canonical
        object.__setattr__(row['source'],'raw',canonical(raw))
    with pytest.raises(Conflict,match='packet/schema changed|source/runtime/grant binding'):
        owner.sources._physical(row)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0


@pytest.mark.parametrize('damage',['schema_write','packet_fifo','partial_close'])
def test_partial_source_material_failure_closes_exact_retained_fds_before_free(model_runtime,monkeypatch,damage):
    owner,bundle,token,observation,claim=model_runtime
    grant=owner.issue_native_model_grant(bundle,token,observation,packet=PACKET,output_schema=OUTPUT_SCHEMA)
    import rlflow.hybrid_native_model_source as source_module
    original=source_module._write_new
    def write(path, raw):
        if path.name=='output.schema.json' and damage in ('schema_write','partial_close'):
            raise OSError('injected schema write failure')
        result=original(path,raw)
        if path.name=='packet.json' and damage=='packet_fifo':
            path.unlink();os.mkfifo(path,0o600)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(source_module,'_write_new',write)
        with pytest.raises((OSError,Conflict)):
            owner.register(bundle,token,observation,claim,request_key='model',scenario='native_model',native_model_grant=grant)
    attempt=owner._attempts['model'];row=owner.sources._attempts[id(claim)]
    assert attempt['source'] is None and row['producer'] is None
    assert any(fd is not None for fd in row['fds'].values())
    if damage=='partial_close':
        with monkeypatch.context() as patch:
            patch.setattr(owner.sources,'_cleanup_attempt',lambda row:(_ for _ in ()).throw(OSError('injected partial close')))
            with pytest.raises(OSError,match='partial close'):owner.stop_to_terminal(attempt['lease'])
        assert owner._current(attempt)['status']=='UNKNOWN' and owner.pool.snapshot()['occupied']==1
        assert attempt['terminal'] is None and any(fd is not None for fd in row['fds'].values())
    owner.stop_to_terminal(attempt['lease'])
    assert row['status']=='CLOSED' and all(fd is None for fd in row['fds'].values())
    assert owner.pool.snapshot()['occupied']==0
    assert owner._current(attempt)['status']=='SETTLED'
