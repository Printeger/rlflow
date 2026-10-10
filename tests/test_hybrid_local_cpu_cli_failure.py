"""Actual CLI negative execution past authority TTL; original STOP only."""
import json

from rlflow import isolated_local_cpu as cli
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
from rlflow.store import Store


def test_real_failure_after_original_ttl_reports_settled_history_without_replay(tmp_path, monkeypatch, capsys):
    tmp_path.chmod(0o700)
    spec={'purpose':'research','code':"""import json,time
d=json.loads(open(WORK+'/measurements.json').read())
mean=sum(d)/len(d)
print(json.dumps({'mean':mean}),flush=True)
time.sleep(65)
raise ArithmeticError('negative experiment: calibration invalid')
""",'inputs':{'measurements.json':'[1.1,0.9,1.2,0.8]'},'seconds':90,
        'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12},
        'acceptance':{'method':'JSON_METRICS_RANGE','metrics':{'mean':{'min':.95,'max':1.05}},'stderr_empty':True}}
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    original=cli.isolated_session
    def approved(parent,spec,*,approved):
        return original(parent,spec,approved=approved,
            confirmation_reader=lambda p,c:'APPROVE '+c['scope_hash'])
    monkeypatch.setattr(cli,'isolated_session',approved)
    status=cli.main(['run','--parent',str(tmp_path),'--spec',str(path),'--approve-isolated-local-cpu'])
    assert status==1
    rows=[]
    for line in capsys.readouterr().out.splitlines():
        try:rows.append(json.loads(line))
        except ValueError:pass
    report=rows[-1];assert report['execution_outcome']=='RESULT_ARCHIVED'
    assert report['result']['execution']['status']=='NONZERO_EXIT' and report['pool_after']['occupied']==0
    view=report['history'];task=view['task'];proof=view['managed_terminal_proof']
    assert task['recorded_phase']=='FIXTURE_SCOPE_STOPPED' and task['recorded_budget_status']=='SETTLED'
    assert task['recorded_wall_seconds']>=65
    assert task['machine_acceptance_status']=='FAIL' and task['independent_review_status']=='NOT_PROVEN'
    assert not task['condition_evidence'] and not task['controls_available']
    assert view['recorded_settled_usage']['experiment_starts']==1
    assert view['recorded_settled_usage']['wall_seconds']==task['recorded_wall_seconds']
    assert proof['configured_local_result']==report['result']
    assert proof['managed_service_proof']['job']['result']=='done'
    assert proof['managed_service_proof']['keeper_kernel_terminal']
    assert report['model_calls']==report['gpu_calls']==0 and not report['autonomous_goal_complete']
    locator=report['historical_recovery'];store=Store.attach_existing(locator['root'],project_id='isolated_local_cpu',data_mode='fixture')
    cold=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=locator['store_epoch'])
    assert cold.task(locator['reservation_id'],timeline=True)==view
    (tmp_path/'negative-report.json').write_text(json.dumps(report))
