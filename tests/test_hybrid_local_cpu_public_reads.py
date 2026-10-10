"""Actual configured local task -> authenticated sanitized original history."""
import json
import pytest
from fastapi.testclient import TestClient
from rlflow.isolated_local_cpu import isolated_session
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader,LocalCpuPublicTaskReader
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.web_api import Project,create_app
from rlflow.web_auth import AuthStore,Credential,Principal


def test_actual_research_authenticated_public_history_no_control_or_private_handles(tmp_path,monkeypatch):
    tmp_path.chmod(0o700)
    spec={'purpose':'research','code':"import json; d=json.loads(open(WORK+'/data.json').read()); print(json.dumps({'mean':sum(d)/len(d)}))",
          'inputs':{'data.json':'[2,3,7,4]'},'seconds':10,
          'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12},
          'acceptance':{'method':'JSON_METRICS_RANGE','metrics':{'mean':{'min':3.9,'max':4.1}},'stderr_empty':True}}
    with isolated_session(tmp_path,spec,approved=True,
            confirmation_reader=lambda proposal,c:'APPROVE '+c['scope_hash']) as session:
        runtime=session['runtime'];project='isolated_local_cpu';epoch=runtime.plans.workspace.store_epoch
        reader=LocalCpuPublicTaskReader(runtime.store,project_id=project,store_epoch=epoch)
        viewer=Principal('viewer','human',{'viewer'},{project});other=Principal('other','human',{'viewer'},{'another'})
        auth=AuthStore([Credential.create(p,'synthetic local history secret phrase') for p in (viewer,other)])
        token,_=auth.issue_bearer(viewer);foreign,_=auth.issue_bearer(other)
        root=Project(project,str(runtime.store.root),'fixture');origin='http://127.0.0.1:8765'
        # Only exact startup-selected sanitized type; raw private SDK reader
        # and arbitrary subclasses remain rejected by the authenticated API.
        with pytest.raises(ValueError):
            create_app([root],auth,origin=origin,fixture_task_readers={project:LocalCpuTaskReader(runtime.store,project_id=project,store_epoch=epoch)})
        app=create_app([root],auth,origin=origin,fixture_task_readers={project:reader})
        reservation=reservation_key(session['reserve']);base='/api/v1/projects/'+project+'/fixture-tasks'
        headers={'Authorization':'Bearer '+token}
        with TestClient(app,base_url=origin) as client:
            assert client.get(base).status_code==401
            assert client.get(base,headers={'Authorization':'Bearer '+foreign}).status_code==404
            before=client.get(base+'/'+reservation+'/timeline',headers=headers).json()
            assert before['configured_result'] is None and before['recorded_settled_usage'] is None
            assert before['task']['machine_acceptance_status']=='UNKNOWN'
            assert runtime.run_local_cpu(session['lease'])['machine_acceptance']['status']=='PASS'
            version=runtime.store.version()
            with monkeypatch.context() as patch:
                patch.setattr(runtime,'poll',lambda *a,**k:pytest.fail('GET must not poll Runtime'))
                patch.setattr(runtime.sources,'poll',lambda *a,**k:pytest.fail('GET must not read live source'))
                page=client.get(base,headers=headers);response=client.get(base+'/'+reservation+'/timeline',headers=headers)
            assert page.status_code==response.status_code==200
            view=response.json();assert page.json()['items']==[view['task']]
            assert view['configured_result']['machine_acceptance']['status']=='PASS'
            assert json.loads(view['configured_result']['outputs']['stdout']['text'])=={'mean':4}
            assert view['recorded_settled_usage']['experiment_starts']==1
            assert view['task']['independent_review_status']=='NOT_PROVEN' and not view['task']['condition_evidence']
            for secret in ('managed_terminal_proof','lease_id','source_id','keeper','boot_id','invocation_id','unit_reference_held','producer',str(runtime.store.root)):
                assert secret not in response.text
            assert not view['task']['controls_available'] and view['task']['current_execution_status']=='UNKNOWN'
            assert client.post(base+'/'+reservation+'/commands',headers=headers,json={'action':'START_FIXED_CPU'}).status_code in (404,405)
            assert client.get(base+'?poll=1',headers=headers).status_code==400
            assert client.get(base,headers={**headers,'Origin':'https://other.invalid'}).status_code==403
            assert runtime.store.version()==version and runtime.pool.snapshot()['occupied']==0
            auth.revoke(token);assert client.get(base,headers=headers).status_code==401
            (tmp_path/'public-task.json').write_text(json.dumps(view))
