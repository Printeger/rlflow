"""CPU integration with EXPLICIT synthetic model-source hooks, never qualification.

Native G is intercepted before exec; only the existing managed CPU runner runs.
The synthetic hooks exercise dispatch wiring, not authentic model provenance.
"""
import hashlib
import json
import subprocess
import copy
import sys
from dataclasses import replace

import pytest

from rlflow.hybrid_a_workflow_profile import registration
from rlflow.hybrid_budget import zero
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.hybrid_engineering_candidate import transform
from rlflow.hybrid_goals import digest
from rlflow.hybrid_local_cpu_profile import module_pins
from rlflow.hybrid_local_cpu_runtime import LocalCpuRunnerOwner
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_usage_source import _RuntimeStartedObservation
from rlflow.hybrid_workspace import SECTIONS as WORKSPACE
from rlflow.store import Conflict,canonical
from tests.test_hybrid_a_workflow_derivation import original,native_setup,workflow_bound,FILES
from tests.test_hybrid_native_model_usage import publication

ACTUAL_POPEN=subprocess.Popen


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live','bound':lambda config:cpu_bound(config)}],indirect=True)
def test_safety_retirement_flag_cannot_forge_original_cpu_handoff(original,native_setup,monkeypatch):
    owner,bundle,token,obs,claim=original
    lease=synthetic_engineer_parent(owner,bundle,token,obs,claim,native_setup[4],monkeypatch)
    cap=owner.prepare_workflow_cpu_input(lease)
    token=owner.controller.renew(token,'handoff_negative',expected_version=owner.store.version(),ttl_seconds=60)['token']
    def before_commit(*args,**kwargs):
        raise OSError('TEST before original Workspace close COMMIT')
    with monkeypatch.context() as broken:
        broken.setattr(owner.workspace,'record',before_commit)
        with pytest.raises(OSError,match='TEST before original'):
            owner.handoff_workflow_cpu(lease,cap,token=token)
    owner.shutdown_safety()
    row=owner._native_cpu_handoffs[id(cap)]
    row['retired']=True
    version=owner.store.version()
    with pytest.raises(PermissionError):
        LocalCpuRunnerOwner(owner.pool,owner.membership,owner.plans,_handoff=(owner,cap))
    assert owner.budget._fixture_runtime is owner and row['child'] is None
    assert id(cap) not in owner._native_cpu_retirements
    assert owner.store.version()==version


def cpu_bound(config):
    registry,proposal=workflow_bound(config)
    row=json.loads(registry._raw);spec=row['tools']['native_model']['definition']['spec']
    spec.update(cpu_modules_sha256=digest(module_pins()),cpu_seconds=30,
        checks="from module.source import parse_entries;assert parse_entries('one\\n\\ntwo')==['one','two'];print('checks passed',flush=True)")
    rows=registration(spec)
    row.update(tools=rows['tools'],commands=rows['commands'],
        evaluation_rules={'workflow_rule':rows['rule']},resource_profile=rows['resources'])
    registry=Registry(row);proposal['registry_bindings']=registry.bindings
    proposal['evaluation_data']['evaluation_rule']['version_hash']=digest(rows['rule'])
    return registry,proposal


def synthetic_engineer_parent(owner,bundle,token,obs,claim,home,monkeypatch):
    auth=home/'auth.json';auth.write_bytes(b'{"synthetic":"NOT_A_TOKEN"}');auth.chmod(0o600)
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='synthetic_parent',
        scenario='native_model',native_model_grant=grant)
    attempt=owner._issued(lease)
    owner.prepare_current_account_cache(lease);launch=owner.prepare_native_launch(lease)
    class NoG:
        def __init__(self,pipe):self.pipe=pipe
        def fileno(self):return self.pipe.fileno()
        @property
        def closed(self):return self.pipe.closed
        def close(self):return self.pipe.close()
        def write(self,data):
            assert data==b'G'
            raise PermissionError('TEST G intercepted; no real model source')
        def flush(self):pytest.fail('never flush model G')
    def no_model(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        process=ACTUAL_POPEN(argv,*args,**kwargs);process.stdin=NoG(process.stdin)
        return process
    with monkeypatch.context() as guarded:
        guarded.setattr(subprocess,'Popen',no_model)
        with pytest.raises(PermissionError,match='TEST G intercepted'):
            owner.start(lease,launch=launch)
    # Deliberate test-only substitution: these are NOT original Source caps.
    ack=_RuntimeStartedObservation(attempt['source'],canonical({'SYNTHETIC_SOURCE_NOT_QUALIFIED':True}))
    monkeypatch.setattr(owner.sources,'_runtime_started',lambda *a:ack)
    attempt['started_ack']=ack
    owner._write_phase(attempt,'STARTED_AS_OBSERVED',cleanup=True)
    patch={'base_sha256':digest(FILES),'edits':[{'path':'module/source.py',
        'before_sha256':'sha256:'+hashlib.sha256(FILES['module/source.py'].encode()).hexdigest(),
        'after':'def parse_entries(text):\n    return [line for line in text.splitlines() if line]\n'}]}
    candidate=transform(FILES,patch,allowed_paths=['module/source.py']);message=canonical(patch).decode()
    def usage(*args):
        if attempt['terminal'] is None:return None
        runtime={'phase':'FIXTURE_SCOPE_STOPPED','origin':attempt['origin'],
            'producer':attempt['producer_identity'],'native_model_handoff_attempted':True,
            'started_ack_sha256':digest(json.loads(ack.raw)),
            'terminal_proof_sha256':digest(attempt['terminal']),
            'wall_seconds':attempt['terminal']['wall_seconds']}
        value=publication(runtime);value['source_id']=attempt['source'].id
        value['output_sha256']='sha256:'+hashlib.sha256(message.encode()).hexdigest()
        return value
    def result(*args):
        counts=usage()
        if counts is None:return None
        return {'profile':'ORIGINAL_NATIVE_RESULT_V1','role':'Engineer',
            'usage_publication_sha256':digest(counts),'message_utf8':message,
            'files':candidate.files(),'candidate_sha256':candidate.output_sha256,
            'allowed_paths':['module/source.py'],'condition_evidence_enabled':False}
    monkeypatch.setattr(owner.sources,'_runtime_usage_publication',usage)
    monkeypatch.setattr(owner.sources,'_runtime_result_publication',result)
    owner.stop_to_terminal(lease)
    assert owner._current(attempt)['status']=='SETTLED' and owner.pool.snapshot()['occupied']==0
    return lease


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live','bound':cpu_bound}],indirect=True)
@pytest.mark.parametrize('fault',['workspace_close','owner_install','owner_shutdown','close_rollback'])
def test_same_approval_cpu_exec_and_lost_workspace_close_ack_without_model(original,native_setup,monkeypatch,fault):
    owner,bundle,token,obs,claim=original
    lease=synthetic_engineer_parent(owner,bundle,token,obs,claim,native_setup[4],monkeypatch)
    cap=owner.prepare_workflow_cpu_input(lease)
    token=owner.controller.renew(token,'handoff_current',expected_version=owner.store.version(),ttl_seconds=60)['token']
    with pytest.raises(PermissionError):
        LocalCpuRunnerOwner(owner.pool,owner.membership,owner.plans,_handoff=(owner,replace(cap)))
    real_record=owner.workspace.record;lost=[False]
    def lost_ack(request,*args,**kwargs):
        if fault=='close_rollback' and request['operation']=='complete_close' and not lost[0]:
            lost[0]=True
            raise OSError('TEST lost before original complete_close COMMIT')
        value=real_record(request,*args,**kwargs)
        if fault=='workspace_close' and request['operation']=='complete_close' and not lost[0]:
            lost[0]=True
            raise OSError('TEST lost original complete_close return')
        return value
    with monkeypatch.context() as broken:
        broken.setattr(owner.workspace,'record',lost_ack)
        if fault=='owner_install':
            real_init=LocalCpuRunnerOwner.__init__
            def lost_install(self,*args,**kwargs):
                real_init(self,*args,**kwargs)
                raise OSError('TEST lost original owner install return')
            broken.setattr(LocalCpuRunnerOwner,'__init__',lost_install)
        if fault=='owner_shutdown':
            real_shutdown=owner.shutdown
            def lost_shutdown():
                real_shutdown()
                raise OSError('TEST lost original owner shutdown return')
            broken.setattr(owner,'shutdown',lost_shutdown)
        with pytest.raises(OSError,match='TEST lost'):
            owner.handoff_workflow_cpu(lease,cap,token=token)
    if fault in ('workspace_close','close_rollback'):assert owner._live and owner.budget._fixture_runtime is owner
    if fault=='close_rollback':
        token=owner.controller.renew(token,'after_close_rollback',expected_version=owner.store.version(),ttl_seconds=60)['token']
    with pytest.raises(PermissionError,match='original registered'):
        copy.copy(owner).handoff_workflow_cpu(lease,cap,token=token)
    cpu=owner.handoff_workflow_cpu(lease,cap,token=token)
    try:
        assert not owner._live and not owner.sources._live
        assert cpu.budget is owner.budget and cpu.budget._fixture_runtime is cpu
        assert owner.handoff_workflow_cpu(lease,cap,token=token) is cpu
        assert owner.workspace.store.objects(WORKSPACE[1])[0][1]['state']=='CLOSED_PRE_RUNTIME'
        plans=cpu.plans;old=cpu._workflow_handoff['parent'];parent=json.loads(old)
        intent=parent['preparation']['intent_key']
        reserve={key:parent['request'][key] for key in ('project_id','data_mode','goal_ref','store_epoch')}
        reserve.update(idempotency_key='new_cpu_reserve',expected_state_version=cpu.store.version(),
            action='RESERVE',preparation_intent_key=intent,amount={**zero(),'wall_seconds':40},purpose='EXECUTION')
        cpu.budget.record(reserve,token)
        observation=cpu.workspace.stage(intent);value=json.loads(observation.raw)
        request={key:reserve[key] for key in ('project_id','data_mode','goal_ref','store_epoch')}
        request.update(idempotency_key='new_cpu_workspace',expected_state_version=cpu.store.version(),
            expected_workspace_revision=0,workspace_id=value['workspace_id'],reservation_id=reservation_key(reserve),
            operation='acquire',ttl_seconds=30)
        cpu.workspace.record(request,token,observation)
        new_plan=plans.prepare_plan(token,observation,'new_cpu_plan')
        plans.persist_intent(new_plan,token,observation,expected_version=cpu.store.version())
        plans.publish(new_plan,token,observation,expected_version=cpu.store.version())
        new_claim=cpu.pool.claim(cpu.membership,expected_version=cpu.pool.snapshot()['version'],request_key='cpu_claim',seconds=60)
        grant=cpu.issue_local_cpu_grant(new_plan,token,observation)
        task=cpu.register(new_plan,token,observation,new_claim,request_key='cpu_task',scenario='local_cpu',local_cpu_grant=grant)
        def actual_cpu_only(argv,*args,**kwargs):
            assert argv[0]=='/usr/bin/systemd-run' and 'hybrid_local_runner_service' in argv[-1]
            return ACTUAL_POPEN(argv,*args,**kwargs)
        monkeypatch.setattr(subprocess,'Popen',actual_cpu_only)
        output=cpu.run_local_cpu(task)
        assert output['machine_acceptance']['status']=='PASS' and not output['condition_evidence']
        assert cpu._current(cpu._issued(task))['status']=='SETTLED' and cpu.pool.snapshot()['occupied']==0
        with pytest.raises(Conflict,match='unique CPU stage'):
            cpu.issue_local_cpu_grant(new_plan,token,observation)
        cpu.store.snapshot();assert cpu.store.recover()==cpu.store.audit()==cpu.store.replay()
    finally:
        original_error=sys.exc_info()[1]
        if cpu._live:
            try:cpu.shutdown()
            except BaseException as cleanup_error:
                cpu.shutdown_safety()
                if original_error is not None:
                    original_error.add_note('CPU cleanup: '+repr(cleanup_error))
                    raise original_error
                raise
