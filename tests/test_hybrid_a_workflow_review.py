"""Actual CPU parent wiring with EXPLICIT synthetic model source; NOT qualification."""
import copy
import json
import subprocess
import sys
from dataclasses import replace

import pytest

from rlflow.hybrid_a_workflow_review import from_cpu
from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_runtime import NativeModelOwner
from rlflow.store import Conflict,canonical
from tests.test_hybrid_a_workflow_cpu_runtime import cpu_bound,synthetic_engineer_parent,ACTUAL_POPEN
from tests.test_hybrid_a_workflow_derivation import original,native_setup


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live','bound':cpu_bound}],indirect=True)
@pytest.mark.parametrize('fault',['workspace_close','normal_shutdown','safety_only'])
def test_reviewer_handoff_original_responsibility_receipts_without_model(original,native_setup,monkeypatch,fault):
    owner,bundle,token,obs,claim=original
    lease=synthetic_engineer_parent(owner,bundle,token,obs,claim,native_setup[4],monkeypatch)
    cap=owner.prepare_workflow_cpu_input(lease)
    token=owner.controller.renew(token,'reviewer_close_fault',expected_version=owner.store.version(),ttl_seconds=60)['token']
    cpu=owner.handoff_workflow_cpu(lease,cap,token=token);reviewer=None;review=None
    def actual_cpu_only(argv,*args,**kwargs):
        assert argv[0]=='/usr/bin/systemd-run' and 'hybrid_local_runner_service' in argv[-1]
        return ACTUAL_POPEN(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',actual_cpu_only)
    try:
        output=cpu.execute_workflow_cpu(token)
        assert output['machine_acceptance']['status']=='PASS'
        task=cpu._workflow_cpu_sequence['lease'];review=cpu.prepare_workflow_reviewer_input(task)
        record=cpu.workspace.record;shutdown=cpu.shutdown
        def broken_record(request,*args,**kwargs):
            if request['operation']=='complete_close' and fault=='safety_only':
                raise OSError('TEST before Reviewer complete close COMMIT')
            result=record(request,*args,**kwargs)
            if request['operation']=='complete_close':
                raise OSError('TEST lost Reviewer complete close return')
            return result
        def broken_shutdown():
            shutdown();raise OSError('TEST lost normal CPU shutdown return')
        with monkeypatch.context() as broken:
            if fault=='normal_shutdown':broken.setattr(cpu,'shutdown',broken_shutdown)
            else:broken.setattr(cpu.workspace,'record',broken_record)
            with pytest.raises(OSError,match='TEST '):
                cpu.handoff_workflow_reviewer(task,review,token=token)
        if fault=='safety_only':
            cpu.shutdown_safety()
            assert not cpu._live and not cpu.sources._live
            row=cpu._review_handoffs[id(review)];row['retired']=True
            versions=(cpu.store.version(),cpu.pool.snapshot()['version'])
            with pytest.raises(PermissionError):
                NativeModelOwner(cpu.pool,cpu.membership,cpu.plans,_review_handoff=(cpu,review))
            assert cpu.budget._fixture_runtime is cpu and row['child'] is None
            assert id(review) not in cpu._review_retirements
            assert (cpu.store.version(),cpu.pool.snapshot()['version'])==versions
        else:
            reviewer=cpu.handoff_workflow_reviewer(task,review,token=token)
            assert reviewer.budget is cpu.budget and reviewer.budget._fixture_runtime is reviewer
            assert not cpu._live and not cpu.sources._live and not reviewer._attempts
            versions=(cpu.store.version(),cpu.pool.snapshot()['version'])
            assert cpu.handoff_workflow_reviewer(task,review,token=token) is reviewer
            assert (cpu.store.version(),cpu.pool.snapshot()['version'])==versions
        cpu.store.snapshot();assert cpu.store.recover()==cpu.store.audit()==cpu.store.replay()
    finally:
        error=sys.exc_info()[1]
        if reviewer is None and review is not None:
            row=cpu._review_handoffs.get(id(review))
            if row is not None:reviewer=row['child']
        if reviewer is not None and reviewer._live:reviewer.shutdown()
        if cpu._live:
            try:cpu.shutdown()
            except BaseException as cleanup:
                cpu.shutdown_safety()
                if error is not None:
                    error.add_note('CPU cleanup: '+repr(cleanup));raise error
                raise


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live','bound':cpu_bound}],indirect=True)
def test_original_cpu_proof_freezes_exact_independent_reviewer_input_without_model(original,native_setup,monkeypatch):
    owner,bundle,token,obs,claim=original
    lease=synthetic_engineer_parent(owner,bundle,token,obs,claim,native_setup[4],monkeypatch)
    cap=owner.prepare_workflow_cpu_input(lease)
    token=owner.controller.renew(token,'reviewer_parent',expected_version=owner.store.version(),ttl_seconds=60)['token']
    cpu=owner.handoff_workflow_cpu(lease,cap,token=token)
    def actual_cpu_only(argv,*args,**kwargs):
        assert argv[0]=='/usr/bin/systemd-run' and 'hybrid_local_runner_service' in argv[-1]
        return ACTUAL_POPEN(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',actual_cpu_only)
    reviewer=None
    try:
        output=cpu.execute_workflow_cpu(token)
        task=cpu._workflow_cpu_sequence['lease']
        attempt=cpu._issued(task);parent=attempt['entries']['FIXTURE_SCOPE_STOPPED']
        versions=(cpu.store.version(),cpu.pool.snapshot()['version'])
        review=cpu.prepare_workflow_reviewer_input(task)
        value=cpu._issued_workflow_reviewer_input(task,review)
        assert value['packet']['role']=='Evaluator' and value['spec']['effort']=='high'
        assert value['packet']['files']==json.loads(cpu._workflow_handoff_raw[1])['request']['fixture_runtime']['native_model_result']['files']
        assert digest(value['packet']['files'])==attempt['origin']['local_cpu']['workflow']['candidate_sha256']
        assert value['machine_result_sha256']==digest(output)
        assert not value['condition_evidence_enabled']
        assert value['parents']['cpu']['hash']==digest(parent)
        assert cpu.prepare_workflow_reviewer_input(task) is review
        value['packet']['files'].clear()
        assert cpu._issued_workflow_reviewer_input(task,review)['packet']['files']
        with pytest.raises(PermissionError):copy.copy(cpu).prepare_workflow_reviewer_input(task)
        with pytest.raises(PermissionError):cpu._issued_workflow_reviewer_input(task,replace(review))
        with pytest.raises(PermissionError):cpu._issued_workflow_reviewer_input(replace(task),review)
        original_raw=attempt['local_result_raw'];attempt['local_result_raw']=canonical({'forged':True})
        try:
            with pytest.raises(Conflict):cpu.prepare_workflow_reviewer_input(task)
        finally:attempt['local_result_raw']=original_raw
        config=json.loads(cpu.plans.registry._raw)
        engineer=json.loads(cpu._workflow_handoff_raw[1])
        # Use original loaded proposal; this loop tests DATA guards only.
        with cpu.store.read_connection() as db:
            from rlflow.hybrid_reads import ReadBudget
            from rlflow.store import PREPARATION_READ_BYTES
            db.execute('BEGIN');loaded=cpu.budget._load(db,parent['request']['goal_ref'],ReadBudget(db,PREPARATION_READ_BYTES))
            proposal=loaded['record']['contract']['proposal']
        for damage in ('unknown','wrong_parent','failed_acceptance','wrong_candidate','changed_epoch'):
            bad=copy.deepcopy(parent)
            runtime=bad['request']['fixture_runtime']
            if damage=='unknown':bad['decision']='UNKNOWN'
            elif damage=='wrong_parent':runtime['origin']['local_cpu']['workflow']['parent']['hash']=digest('wrong')
            elif damage=='failed_acceptance':runtime['local_cpu_terminal_proof']['configured_local_result']['machine_acceptance']['status']='FAIL'
            elif damage=='wrong_candidate':runtime['origin']['local_cpu']['workflow']['candidate_sha256']=digest('wrong')
            elif damage=='changed_epoch':bad['request']['store_epoch']='wrong_epoch'
            with pytest.raises(Conflict):from_cpu(proposal,config,bad,engineer)
        assert (cpu.store.version(),cpu.pool.snapshot()['version'])==versions
        assert cpu.pool.snapshot()['occupied']==0
        cpu.store.snapshot();assert cpu.store.recover()==cpu.store.audit()==cpu.store.replay()
        with pytest.raises(PermissionError):
            NativeModelOwner(cpu.pool,cpu.membership,cpu.plans,_review_handoff=(cpu,replace(review)))
        real_init=NativeModelOwner.__init__
        def lost_install(self,*args,**kwargs):
            real_init(self,*args,**kwargs)
            raise OSError('TEST lost Reviewer owner install return')
        with monkeypatch.context() as broken:
            broken.setattr(NativeModelOwner,'__init__',lost_install)
            with pytest.raises(OSError,match='TEST lost Reviewer owner install'):
                cpu.handoff_workflow_reviewer(task,review,token=token)
        assert not cpu._live and not cpu.sources._live
        with pytest.raises(PermissionError):copy.copy(cpu).handoff_workflow_reviewer(task,review,token=token)
        reviewer=cpu.handoff_workflow_reviewer(task,review,token=token)
        assert reviewer.budget is cpu.budget and reviewer.budget._fixture_runtime is reviewer
        assert reviewer._review_parent_raw==(canonical(json.loads(review.raw)),canonical(parent))
        assert cpu.handoff_workflow_reviewer(task,review,token=token) is reviewer
        assert not reviewer._attempts
        versions=(reviewer.store.version(),reviewer.pool.snapshot()['version'])
        # Owner transfer is NOT a first-Engineer reset or a generating grant.
        with pytest.raises((Conflict,PermissionError)):
            reviewer.issue_workflow_engineer_grant(bundle,token,obs,files={})
        assert (reviewer.store.version(),reviewer.pool.snapshot()['version'])==versions
        reviewer.store.snapshot();assert reviewer.store.recover()==reviewer.store.audit()==reviewer.store.replay()
    finally:
        error=sys.exc_info()[1]
        if reviewer is None:
            entry=cpu._review_handoffs.get(id(review)) if 'review' in locals() else None
            if entry is not None:reviewer=entry['child']
        if reviewer is not None and reviewer._live:reviewer.shutdown()
        if cpu._live:
            try:cpu.shutdown()
            except BaseException as cleanup:
                cpu.shutdown_safety()
                if error is not None:
                    error.add_note('CPU cleanup: '+repr(cleanup));raise error
                raise
