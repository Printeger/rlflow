"""Private two-project original-pool HTTP/Chrome fixture; no paid/GPU state."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from tests.test_execution_adapter import setup as native_setup
from tests import test_hybrid_finite_host_app as shared_app

def main():
    mode=sys.argv[2] if len(sys.argv)>2 else None
    if mode not in (None,'machine-failures','unknown-start'):raise ValueError('closed fixture fault mode')
    root=Path(sys.argv[1]).resolve();sock=socket.socket();sock.bind(('127.0.0.1',0))
    origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
    patch=pytest.MonkeyPatch();patch.setattr(shared_app,'ORIGIN',origin)
    native=native_setup.__wrapped__(root,patch)
    fixture=shared_app.application.__wrapped__(root,native,patch)
    host,units,services,observers,app,token,headers=next(fixture)
    launches=[];writes=[];releases=[];collections=[];lost_children=[];reconciliations=[];faults=[];spawn=subprocess.Popen;pwrite=os.pwrite
    def counted_spawn(*a,**kw):
        child=spawn(*a,**kw);launches.append(a[0])
        if mode=='unknown-start' and a[0][7]=='cpu_trial':
            lost_children.append(child);raise OSError('real original fixture child started, Popen return lost')
        return child
    patch.setattr(subprocess,'Popen',counted_spawn)
    patch.setattr(os,'pwrite',lambda fd,data,offset:(writes.append(True),pwrite(fd,data,offset))[1])
    for u,observer in zip(units,observers):
        register=u.runtime._register_release
        def sample(attempt,_register=register,_observer=observer):
            result=_register(attempt);assert _observer.sample();return result
        patch.setattr(u.runtime,'_register_release',sample)
    hold_index=[None];entered=threading.Event();release=threading.Event();release.set()
    if mode is not None:
        for index,(unit,service) in enumerate(zip(units,services)):
            original=unit.runtime.sources._runtime_release
            def released(*a,_original=original,_index=index,**kw):
                releases.append(_index);return _original(*a,**kw)
            patch.setattr(unit.runtime.sources,'_runtime_release',released)
            original=unit._collect
            def collected(*a,_original=original,_index=index,**kw):
                collections.append(_index);return _original(*a,**kw)
            patch.setattr(unit,'_collect',collected)
            if mode=='machine-failures':
                name='decide' if index==0 else 'accept_machine';original=getattr(unit.output,name)
                def missing(*a,_index=index,_output=unit.output,_name=name,_original=original,**kw):
                    setattr(_output,_name,_original)
                    if _index==1:_original(*a,**kw)
                    faults.append(_index);raise OSError('original fixture machine stage return missing')
                patch.setattr(unit.output,name,missing)
            original=service._reconcile_source
            def held(command,_index=index,_original=original):
                if hold_index[0]==_index:
                    entered.set()
                    if not release.wait(12):raise TimeoutError('bounded private fixture read gate')
                return _original(command)
            patch.setattr(service,'_reconcile_source',held)
            original=service.execute_reconcile_prepared
            def verified(operation,_index=index,_service=service,_unit=unit,_original=original):
                before=_service.store.version();l=len(launches);w=len(writes);g=len(releases);c=len(collections)
                # Assertions surround the actual original command operation,
                # not a synthetic response or fabricated result capability.
                result=_original(operation)
                assert len(launches)==l and len(writes)==w and len(releases)==g and len(collections)==c
                reconciliations.append({'project':_index,'status':result['result']['status'],
                    'new_events':_service.store.version()-before,'launch_delta':len(launches)-l,
                    'write_delta':len(writes)-w,'G_delta':len(releases)-g,'collect_delta':len(collections)-c,'result_fact':result['result_fact']})
                return result
            patch.setattr(service,'execute_reconcile_prepared',verified)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    def inspect():
        return {'launches':len(launches),'writes':len(writes),'occupied':host.pool.snapshot()['occupied'],
            'faults':faults,'held':entered.is_set(),'reconciliations':reconciliations,'G_count':len(releases),'collect_count':len(collections),
            'projects':[{'id':s.project_id,'version':s.store.version(),'cancelled':u._cancelled.is_set(),
                'status':None if u._last is None else u._last['status'],
                'machine_facts':sum('machine_verification' in v for k,v in s.store.objects('hybrid_cpu_trial_assessments') if k) if index==0 else
                    sum('machine_verification' in v for k,v in s.store.objects('hybrid_candidate_output_results') if k),
                'experiment_balance':s.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']}
                for index,(s,u) in enumerate(zip(services,units))]}
    def controls():
        try:
            for line in sys.stdin:
                op=json.loads(line)['op']
                if op=='stop':break
                if mode is not None and op=='hold_engineering':
                    hold_index[0]=1;entered.clear();release.clear();print(json.dumps({'armed':True}),flush=True);continue
                if mode is not None and op=='release':
                    hold_index[0]=None;release.set();print(json.dumps({'released':True}),flush=True);continue
                if mode is not None and op=='close_engineering':
                    units[1].runtime.shutdown();print(json.dumps({'closed':True}),flush=True);continue
                if op!='inspect':raise ValueError('unknown private operation')
                print(json.dumps(inspect()),flush=True)
        finally:release.set();server.should_exit=True
    threading.Thread(target=controls,daemon=True).start()
    print(json.dumps({'origin':origin,'principal':'fixture_human','phrase':shared_app.PHRASE,
        'projects':[s.project_id for s in services]}),flush=True)
    try:server.run(sockets=[sock])
    finally:
        release.set()
        for child in lost_children:
            child.wait(timeout=5)
            if child.stdin is not None:child.stdin.close()
        if mode=='unknown-start' and units[0].runtime._live:units[0].runtime.shutdown_safety()
        fixture.close();patch.undo();sock.close()

if __name__=='__main__':main()
