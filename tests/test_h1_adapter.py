"""CPU-only tests. Real reviewed H1 lifecycle is loaded; GPU construction is replaced."""
import copy,importlib,json,os,sys,types
from pathlib import Path
import pytest
from rlflow import h1,experiments
from rlflow.store import atomic,canonical,Conflict
from rlflow.jobs import identity

WORK=experiments.DISPATCHER.parents[2]
pytestmark = pytest.mark.skipif(not experiments.DISPATCHER.is_file(), reason="External H1 implementation excluded")

@pytest.fixture
def adapter(monkeypatch):
    # No product modification, bytecode, torch, simulator, or real authorization.
    monkeypatch.setattr(sys,'dont_write_bytecode',True)
    monkeypatch.syspath_prepend(str(WORK))
    package=types.ModuleType('_offline_h1');package.__path__=[str(WORK/'training_workloads/unified_h1')]
    monkeypatch.setitem(sys.modules,'_offline_h1',package)
    backend=types.ModuleType('_offline_h1.backend')
    def forbidden(**kw):raise AssertionError('GPU backend must never be constructed')
    backend.create_live_backend=forbidden
    monkeypatch.setitem(sys.modules,'_offline_h1.backend',backend)
    evaluation=types.ModuleType('_offline_h1.evaluation');evaluation.CASE_ORDER=('Z','T','S','X','W')
    monkeypatch.setitem(sys.modules,'_offline_h1.evaluation',evaluation)
    return importlib.import_module('_offline_h1.live_adapter'),importlib.import_module('_offline_h1.budget')

@pytest.fixture
def bound(tmp_path,monkeypatch,adapter):
    _,budget=adapter;work=tmp_path/'work';entry=work/'training_workloads/unified_h1';entry.mkdir(parents=True)
    for name in ('candidate_config.json','formal_unified_h1.py','local_dispatch.py'):(entry/name).write_text('{}')
    attempt=tmp_path/'attempt';(attempt/'results').mkdir(parents=True)
    authfile=tmp_path/'auth.json';authfile.write_text('{}');product=tmp_path/'product'
    pin=experiments.file_pin(sys.executable)
    config={'training':{'seed':123},'method':{'version':'unified-h1-v1'},'versions':{'metric':'metric-h1-v1'},
            'execution':{'frozen_runtime_root':'frozen-runtime'},'product':{'path':str(product)}}
    auth={'mode':'controlled-failure','parameters':{},'budgets':budget.required_mode_budget('controlled-failure',{}),
          'authorization_sha256':h1.digest(authfile)}
    value={'cwd':str(work),'h1':{'workload_root':str(work),'attempt':str(attempt),'mode':'controlled-failure',
             'config_sha256':h1.digest(entry/'candidate_config.json'),'gpu_devices':['0'],'gpu_accounting':'allocated_device_wall_seconds'},
           'pins':{'workload':{'path':str(entry/'formal_unified_h1.py')},'dispatcher':{'path':str(entry/'local_dispatch.py')},
            'authorization':experiments.file_pin(authfile),'executable':pin,'runtime':pin,
            'product':{'path':str(product/'isaaclab-training/instinctlab/envs/unified_h1_direct_env.py')}},
           'method':'unified-h1-v1','evaluation':'metric-h1-v1','runtime':'frozen-runtime','seed':123,
           'resources':{'starts':1,'wall_seconds':610,'gpu_seconds':610,'transitions':0},
           'observations':['status','counters','process_identity','process_start']}
    value['argv']=[pin['path'],'-B','-m','training_workloads.unified_h1.formal_unified_h1','--authorization',str(authfile),'--attempt',str(attempt),'--mode','controlled-failure']
    observed={'config':config,'authorization':auth}
    monkeypatch.setattr(h1,'inspect_authority',lambda _:copy.deepcopy(observed))
    d=tmp_path/'job';d.mkdir();atomic(d/'h1-authority.json',canonical(observed));atomic(d/'process-identity.json',canonical(identity(os.getpid())))
    return value,observed,d


def test_exact_h1_binding_and_consumed_attempt(bound):
    v,observed,d=bound
    assert h1.validate(v,d)==observed
    (Path(v['h1']['attempt'])/'results/controlled-failure').mkdir()
    with pytest.raises(Conflict,match='already consumed'):h1.validate(v,d)

@pytest.mark.parametrize('change',[
    lambda v:v['argv'].append('--extra'),lambda v:v['resources'].update(gpu_seconds=609),
    lambda v:v.update(seed=124),lambda v:v['h1'].update(config_sha256='0'*64),
    lambda v:v['h1'].update(gpu_devices=['1']),lambda v:v.update(observations=['stdout']),
    lambda v:v['pins']['product'].update(path='/tmp/wrong')])
def test_h1_drift_rejected(bound,change):
    v,_,d=bound;change(v)
    with pytest.raises(Conflict):h1.validate(v,d)


def test_actual_reviewed_lifecycle_cpu_failure_raw_collection_and_no_retry(bound,adapter):
    v,observed,d=bound;live,_=adapter;attempt=Path(v['h1']['attempt']);calls=[]
    def cpu_factory(**kw):calls.append(1);raise RuntimeError('offline injected construction failure; no simulator')
    assert live.run_main_sequence(authorization=observed['authorization'],attempt=attempt,backend_factory=cpu_factory)==1
    receipt={'status':'FAILED','allocated_seconds':.25}
    result=h1.collect(v,d,receipt)
    assert result['counter_completeness']=='FINAL' and result['transitions']==0
    assert result['counters']['live_process_starts']==1 and result['counters']['simulator_initializations']==1
    assert result['raw_status']=='FAIL' and result['scientific_validity']=='UNASSESSED' and result['formal_verdict']=='NOT_GRANTED'
    assert 'status.json' in result['manifest'] and h1.collect(v,d,receipt)==result
    with pytest.raises(ValueError):live.run_main_sequence(authorization=observed['authorization'],attempt=attempt,backend_factory=cpu_factory)
    assert calls==[1]


def test_pending_or_missing_raw_counters_retain_unknown_dimensions(bound,adapter):
    v,observed,d=bound;output=Path(v['h1']['attempt'])/'results/controlled-failure';output.mkdir()
    atomic(output/'status.json',canonical({'status':'FAIL_PENDING_CLOSE','counters':{'training_transitions':0}}))
    result=h1.collect(v,d,{'status':'FAILED','allocated_seconds':None})
    assert result['transitions'] is None and result['allocation_gpu_seconds'] is None


def test_raw_counter_overspend_is_not_silently_settled(bound):
    v,_,d=bound;output=Path(v['h1']['attempt'])/'results/controlled-failure';output.mkdir()
    atomic(output/'status.json',canonical({'status':'FAIL','counters':{'training_transitions':1}}))
    with pytest.raises(Conflict,match='exceeds authority'):h1.collect(v,d,{'status':'FAILED','allocated_seconds':1})


def test_original_authorization_checker_exact_binding_and_rejection(bound,monkeypatch):
    v,observed,d=bound
    auth=importlib.import_module('_offline_h1.authorization')
    config={**observed['config'],'resolved_identity':{'product_commit':'a','product_tree':'b','workload_commit':'c','workload_tree':'d'}}
    monkeypatch.setattr(auth,'load_config',lambda:config)
    path=Path(v['pins']['authorization']['path']);attempt=Path(v['h1']['attempt'])
    value={'schema_version':'unified-h1-r3-authorization.v2','status':'AUTHORIZED','order_id':'UNIFIED-H1-R3',
           'method_sha256':auth.METHOD_SHA256,'config_sha256':auth.sha256_file(auth.CONFIG_PATH),
           **config['resolved_identity'],'attempt':str(attempt),'mode':'controlled-failure','parameters':{},'budgets':observed['authorization']['budgets']}
    atomic(path,canonical(value))
    assert auth.load_r3_authorization(path,attempt,'controlled-failure')['budgets']==value['budgets']
    for field in ('status','method_sha256','product_commit','config_sha256','order_id'):
        invalid={**value,field:'unapproved-or-drifted'};atomic(path,canonical(invalid))
        with pytest.raises(PermissionError):auth.load_r3_authorization(path,attempt,'controlled-failure')


def test_late_raw_evidence_settles_reserved_dimensions_without_second_start(bound,adapter,tmp_path):
    from rlflow.store import Store,sha
    v,observed,d=bound;live,_=adapter;store=Store(tmp_path/'state');jid='J-h1-offline';jobdir=store.root/'jobs'/jid
    jobdir.mkdir(parents=True);atomic(jobdir/'h1-authority.json',canonical(observed));atomic(jobdir/'process-identity.json',canonical(identity(os.getpid())))
    v.update(backend='real');receipt={'job_id':jid,'spec_sha256':sha(v),'status':'FAILED','released':True,'elapsed_seconds':.5,'allocated_seconds':.25}
    atomic(jobdir/'receipt.json',canonical(receipt))
    store.transact('OFFLINE_FIXTURE','h1',lambda s:s['jobs'].update({jid:{'id':jid,'spec':v,'status':'RUNNING','identity':None,'reserved_resources':v['resources'],'used_resources':{}}}))
    first=experiments.reconcile(store,jid)
    assert first['used_resources']['starts']==1 and first['reserved_resources']=={'transitions':0}
    def fail(**kw):raise RuntimeError('offline CPU construction failure')
    live.run_main_sequence(authorization=observed['authorization'],attempt=Path(v['h1']['attempt']),backend_factory=fail)
    second=experiments.reconcile(Store(store.root),jid)
    assert second['used_resources']=={'starts':1,'wall_seconds':.5,'gpu_seconds':.25,'transitions':0}
    assert not second['reserved_resources'] and len(list((jobdir/'h1-collections').glob('*.json')))==2
    assert experiments.reconcile(store,jid)==second


def test_reviewed_controlled_failure_closes_both_resources_and_collects_final(bound,adapter):
    v,observed,d=bound;live,_=adapter;attempt=Path(v['h1']['attempt']);calls=[]
    class Resource:
        h1_initialization_physics_ticks=0
        h1_initialization_tick_source='CPU fixture'
        def __init__(self,name):self.name=name
        def close(self):calls.append(self.name+'.close')
    class Backend:
        def resource_check(self,stage,ordinal):calls.append(stage)
        def initial_raw_rays(self):self.counters.reserve_reset(automatic=False,maximum=1);calls.append('initial_raw_rays')
        def preserve(self,status,outcome=None):live._persist(attempt/'results/controlled-failure',self.counters,status,self.initialization_measurement,outcome)
    def factory(**kw):
        b=Backend();b.counters=kw['counters'];b.environment=Resource('environment')
        kw['resources'].update(environment=b.environment,app=Resource('app'));return b
    assert live.run_main_sequence(authorization=observed['authorization'],attempt=attempt,backend_factory=factory)==1
    result=h1.collect(v,d,{'status':'FAILED','allocated_seconds':.25})
    assert calls[-2:]==['environment.close','app.close']
    assert result['raw_status']=='EXPECTED_CONTROLLED_FAILURE' and result['counter_completeness']=='FINAL'
    assert result['counters']['explicit_resets']==1 and result['transitions']==0
    assert result['formal_verdict']=='NOT_GRANTED'
