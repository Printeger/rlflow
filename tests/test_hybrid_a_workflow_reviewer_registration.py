"""Reviewer admission from actual CPU, synthetic Engineer; no model qualification."""
import copy
import json
import subprocess

import pytest

from rlflow.hybrid_budget import account_key
from rlflow.hybrid_budget_ledger import SECTIONS as BUDGET
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict
from tests.test_hybrid_a_workflow_cpu_runtime import cpu_bound,synthetic_engineer_parent,ACTUAL_POPEN
from tests.test_hybrid_a_workflow_derivation import original,native_setup,FILES


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live','bound':cpu_bound}],indirect=True)
def test_reviewer_original_registration_no_model_stop_and_replay(original,native_setup,monkeypatch):
    owner,bundle,token,obs,claim=original
    lease=synthetic_engineer_parent(owner,bundle,token,obs,claim,native_setup[4],monkeypatch)
    cap=owner.prepare_workflow_cpu_input(lease)
    token=owner.controller.renew(token,'review_register',expected_version=owner.store.version(),ttl_seconds=60)['token']
    cpu=owner.handoff_workflow_cpu(lease,cap,token=token);reviewer=None
    def actual_cpu_only(argv,*args,**kwargs):
        assert argv[0]=='/usr/bin/systemd-run' and 'hybrid_local_runner_service' in argv[-1]
        return ACTUAL_POPEN(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',actual_cpu_only)
    try:
        output=cpu.execute_workflow_cpu(token)
        assert output['machine_acceptance']['status']=='PASS'
        task=cpu._workflow_cpu_sequence['lease'];review=cpu.prepare_workflow_reviewer_input(task)
        reviewer=cpu.handoff_workflow_reviewer(task,review,token=token)
        token=reviewer.controller.renew(token,'review_plan',expected_version=reviewer.store.version(),ttl_seconds=60)['token']
        bundle,obs=reviewer.prepare_workflow_reviewer_plan(token)
        assert bundle is reviewer._review_plan_sequence['bundle']
        grant=reviewer.issue_workflow_reviewer_grant(bundle,token,obs)
        binding=json.loads(grant.raw)
        assert binding['role']=='Evaluator' and binding['effort']=='high'
        assert binding['workflow']['stage']=='INDEPENDENT_REVIEW'
        assert binding['workflow']['files']!=FILES
        assert binding['candidate_sha256']==digest(binding['workflow']['files'])
        claim=reviewer.pool.claim(reviewer.membership,expected_version=reviewer.pool.snapshot()['version'],
            request_key='review_claim',seconds=60)
        lease=reviewer.register(bundle,token,obs,claim,request_key='review_register',
            scenario='native_model',native_model_grant=grant)
        attempt=reviewer._issued(lease)
        assert attempt['intent']['plan']['packet']['role']=='Evaluator'
        assert not attempt['intent']['plan']['write_roots']
        packet=json.loads(reviewer._native_model_grants[id(grant)]['packet_raw'])
        assert packet['files']==binding['workflow']['files']
        monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('Reviewer model not authorized'))
        with pytest.raises(PermissionError):reviewer.start(lease)
        reviewer.stop_to_terminal(lease)
        assert reviewer._current(attempt)['status']=='SETTLED'
        assert reviewer.pool.snapshot()['occupied']==0
        head=reviewer.store.get(BUDGET[1],account_key(attempt['ready']['source_context']['budget_reservation']['scope']))
        assert head['workflow']['medium_sessions']==1 and head['workflow']['high_sessions']==1
        assert head['workflow']['controlled_seconds_charged']==660
        assert len(head['workflow']['review_entries'])==1
        versions=(reviewer.store.version(),reviewer.pool.snapshot()['version'])
        with pytest.raises(Conflict,match='quota or unique stage'):
            reviewer.issue_workflow_reviewer_grant(bundle,token,obs)
        assert (reviewer.store.version(),reviewer.pool.snapshot()['version'])==versions
        from rlflow.hybrid_a_workflow_accounting import advance
        registered=attempt['entries']['REGISTER_NO_HANDOFF']
        prior=registered['prior_goal']['workflow']
        for damage in ('foreign_cpu','wrong_role','high_quota','short_charge','duplicate'):
            bad=copy.deepcopy(registered);before=copy.deepcopy(prior)
            native=bad['request']['fixture_runtime']['origin']['native_model']
            if damage=='foreign_cpu':native['workflow']['cpu_registration']='foreign_cpu'
            elif damage=='wrong_role':native['role']='Engineer'
            elif damage=='high_quota':before['high_sessions']=2
            elif damage=='short_charge':bad['prior_reservation']['amount']['wall_seconds']=1
            else:before=copy.deepcopy(head['workflow'])
            with pytest.raises(Conflict):advance(bad,before)
        assert all(fd is None for fd in reviewer.sources._issued(attempt['source'])['fds'].values())
        reviewer.store.snapshot()
        assert reviewer.store.recover()==reviewer.store.audit()==reviewer.store.replay()
    finally:
        if reviewer is not None and reviewer._live:reviewer.shutdown()
        if cpu._live:cpu.shutdown()
