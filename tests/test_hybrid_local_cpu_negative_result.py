"""Actual failed tasks preserve logs, not scientific success or replay."""
import copy
import json
import pytest
from rlflow.isolated_local_cpu import isolated_session
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader,LocalCpuPublicTaskReader
from rlflow.hybrid_local_cpu_result import validate_result
from rlflow.store import Store,Conflict


@pytest.mark.parametrize('failure',['nonzero','deadline'])
def test_actual_negative_result_archived_stopped_and_cold(tmp_path,failure):
    tmp_path.chmod(0o700)
    code="import json,time; print(json.dumps({'loss':0.1}),flush=True); "
    code+="raise ArithmeticError('invalid calibration')" if failure=='nonzero' else 'time.sleep(40)'
    spec={'purpose':'research','code':code,'inputs':{},'seconds':10,
        'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12},
        'acceptance':{'method':'JSON_METRICS_RANGE','metrics':{'loss':{'min':0,'max':.2}},'stderr_empty':False}}
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=lambda p,c:'APPROVE '+c['scope_hash']) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        result=runtime.run_local_cpu(lease)
        assert result['execution']['status'] in (('NONZERO_EXIT',) if failure=='nonzero' else ('DEADLINE','SIGNAL_EXIT'))
        assert result['machine_acceptance']['status']=='FAIL'
        assert json.loads(result['outputs']['stdout']['text'])=={'loss':.1}
        if failure=='nonzero':assert 'invalid calibration' in result['outputs']['stderr']['text']
        row=runtime.sources._issued(attempt['source']);closed=row['task_closed']
        validate_result(result,attempt['origin'],closed['task'],closed['stopped'],spec)
        for mutate in (lambda v:v['execution'].update(wait_status=0),
                       lambda v:v['execution'].update(status='SUCCEEDED'),
                       lambda v:v['machine_acceptance'].update(status='PASS'),
                       lambda v:v['outputs']['stderr'].update(text='hidden failure')):
            bad=copy.deepcopy(result);mutate(bad)
            with pytest.raises(Conflict):validate_result(bad,attempt['origin'],closed['task'],closed['stopped'],spec)
        assert runtime.pool.snapshot()['occupied']==0 and runtime._current(attempt)['status']=='SETTLED'
        version=runtime.store.version()
        assert runtime.run_local_cpu(lease)==result and runtime.store.version()==version
        key=reservation_key(session['reserve']);epoch=runtime.plans.workspace.store_epoch;root=runtime.store.root
        reader=LocalCpuTaskReader(runtime.store,project_id='isolated_local_cpu',store_epoch=epoch)
        history=reader.task(key,timeline=True)
        assert history['recorded_settled_usage']['experiment_starts']==1
        assert history['task']['machine_acceptance_status']=='FAIL' and not history['task']['condition_evidence']
        public=LocalCpuPublicTaskReader(runtime.store,project_id='isolated_local_cpu',store_epoch=epoch).task(key,timeline=True)
        assert public['configured_result']['execution']==result['execution']
        assert 'managed_terminal_proof' not in public
    cold=LocalCpuTaskReader(Store.attach_existing(root,project_id='isolated_local_cpu',data_mode='fixture'),
        project_id='isolated_local_cpu',store_epoch=epoch)
    assert cold.task(key,timeline=True)==history
    (tmp_path/'negative-public.json').write_text(json.dumps(public))
