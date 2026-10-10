"""CLI reporting contract only; stubs do not qualify runtime or STOP."""
from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from rlflow import isolated_local_cpu as cli
from rlflow import hybrid_local_cpu_reads as reads


@pytest.mark.parametrize('status,exit_code', [('PASS',0),('FAIL',1),('NOT_CONFIGURED',2)])
def test_existing_result_exit_codes_preserved_and_final_report_after_context(tmp_path,monkeypatch,capsys,status,exit_code):
    path=tmp_path/'spec.json'
    path.write_text(json.dumps({'purpose':'engineering','code':'print(1)','inputs':{},'seconds':1,
        'limits':{'memory_max':33554432,'cpu_max':'100000 100000','pids_max':2}}))
    order=[]
    def run(lease):order.append('run');return {'machine_acceptance':{'status':status}}
    runtime=SimpleNamespace(store=SimpleNamespace(root=tmp_path),plans=SimpleNamespace(workspace=SimpleNamespace(store_epoch='epoch')),
        run_local_cpu=run,pool=SimpleNamespace(snapshot=lambda:{'occupied':0}))
    @contextmanager
    def context(*args,**kwargs):
        yield {'runtime':runtime,'lease':object(),'reserve':{}}
        # Report must NOT appear while original context is still unclosed.
        assert 'execution_outcome' not in capsys.readouterr().out
        order.append('closed')
    monkeypatch.setattr(cli,'isolated_session',context)
    monkeypatch.setattr(cli,'reservation_key',lambda reserve:'reservation')
    monkeypatch.setattr(reads,'LocalCpuTaskReader',lambda *a,**k:SimpleNamespace(task=lambda *a,**k:{'history':'stub'}))
    assert cli.main(['run','--parent',str(tmp_path),'--spec',str(path),'--approve-isolated-local-cpu'])==exit_code
    assert order==['run','closed']
    report=json.loads(capsys.readouterr().out)
    assert report['execution_outcome']=='RESULT_ARCHIVED' and report['result']['machine_acceptance']['status']==status


def test_context_failure_cannot_publish_final_report_or_suppress_cleanup_error(tmp_path,monkeypatch,capsys):
    path=tmp_path/'spec.json'
    path.write_text(json.dumps({'purpose':'engineering','code':'print(1)','inputs':{},'seconds':1,
        'limits':{'memory_max':33554432,'cpu_max':'100000 100000','pids_max':2}}))
    calls=[]
    def fail(lease):calls.append('run');raise RuntimeError('task unavailable')
    runtime=SimpleNamespace(store=SimpleNamespace(root=tmp_path),plans=SimpleNamespace(workspace=SimpleNamespace(store_epoch='epoch')),
        run_local_cpu=fail,pool=SimpleNamespace(snapshot=lambda:{'occupied':1}))
    @contextmanager
    def context(*args,**kwargs):
        yield {'runtime':runtime,'lease':object(),'reserve':{}}
        raise RuntimeError('original cleanup incomplete')
    monkeypatch.setattr(cli,'isolated_session',context)
    monkeypatch.setattr(cli,'reservation_key',lambda reserve:'reservation')
    monkeypatch.setattr(reads,'LocalCpuTaskReader',lambda *a,**k:SimpleNamespace(task=lambda *a,**k:{'history':'stub'}))
    with pytest.raises(RuntimeError,match='original cleanup incomplete'):
        cli.main(['run','--parent',str(tmp_path),'--spec',str(path),'--approve-isolated-local-cpu'])
    output=capsys.readouterr().out
    assert 'historical_recovery' in output and 'execution_outcome' not in output
    assert calls==['run']
