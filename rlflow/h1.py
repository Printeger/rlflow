"""Control-plane bridge to H1's frozen authorization, entry and raw counters.

No product/runtime edits and no simulator imports in the control plane. Real
execution always traverses the existing formal entry and live_adapter.
"""
import hashlib,json,math,os,subprocess
from pathlib import Path
from .store import Conflict,sha,atomic,canonical


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def inspect_authority(spec):
    """Run only the reviewed, stdlib-only config/authorization checks."""
    h=spec['h1'];root=Path(h['workload_root']);config=json.loads((root/'training_workloads/unified_h1/candidate_config.json').read_text())
    python=Path(config['execution']['python_path'])
    if str(python)!=spec['argv'][0] or digest(python)!=config['execution']['python_sha256']:
        raise Conflict('H1 frozen interpreter binding mismatch')
    # Check complete source hashes before importing the authorization checker.
    for section in ('product','workload'):
        info=config[section];base=Path(info['path'])
        for relative,expected in info['source_sha256'].items():
            path=base/relative
            if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()) or digest(path)!=expected:
                raise Conflict('H1 source manifest drift: '+relative)
    program='''import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
from training_workloads.unified_h1.config import load_config
from training_workloads.unified_h1.authorization import load_r3_authorization
c=load_config();a=load_r3_authorization(Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4])
print(json.dumps({'config':c,'authorization':a},sort_keys=True))
'''
    env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','CUDA_VISIBLE_DEVICES':''}
    result=subprocess.run([str(python),'-I','-B','-c',program,str(root),spec['pins']['authorization']['path'],h['attempt'],h['mode']],
                          cwd=root,env=env,capture_output=True,text=True,timeout=30)
    if result.returncode:raise Conflict('H1 authorization checker rejected: '+result.stderr[-3000:])
    return json.loads(result.stdout)


def validate(spec,root,*,fresh=True):
    h=spec.get('h1')
    if not isinstance(h,dict) or set(h)!={'workload_root','attempt','mode','config_sha256','gpu_devices','gpu_accounting'}:
        raise Conflict('real H1 requires complete adapter binding')
    if h['gpu_devices']!=['0'] or h['gpu_accounting']!='allocated_device_wall_seconds':
        raise Conflict('H1 requires exact device 0 and declared allocation-time accounting')
    work=Path(h['workload_root']);attempt=Path(h['attempt'])
    if not work.is_absolute() or work.is_symlink() or work.resolve()!=work or not attempt.is_absolute() or attempt.is_symlink() or attempt.resolve()!=attempt:
        raise Conflict('H1 paths must be exact resolved paths')
    config_path=work/'training_workloads/unified_h1/candidate_config.json'
    if digest(config_path)!=h['config_sha256']:raise Conflict('H1 config drift')
    if spec['cwd']!=str(work) or spec['pins']['workload']['path']!=str(work/'training_workloads/unified_h1/formal_unified_h1.py') or spec['pins']['dispatcher']['path']!=str(work/'training_workloads/unified_h1/local_dispatch.py'):
        raise Conflict('H1 workload/dispatcher binding mismatch')
    expected=[spec['pins']['executable']['path'],'-B','-m','training_workloads.unified_h1.formal_unified_h1','--authorization',spec['pins']['authorization']['path'],'--attempt',str(attempt),'--mode',h['mode']]
    if spec['argv']!=expected:raise Conflict('real runner must execute the exact reviewed H1 formal entry')
    if not attempt.is_dir() or not (attempt/'results').is_dir():raise Conflict('H1 attempt results root absent')
    if fresh and ((attempt/'results'/h['mode']).exists() or list((attempt/'results').glob('*/process_start.json'))):
        raise Conflict('H1 attempt start budget already consumed')
    observed=inspect_authority(spec);config=observed['config'];auth=observed['authorization']
    budget=auth['budgets'];limit=budget['wall_seconds']+10
    if spec['resources']!={'starts':1,'wall_seconds':limit,'gpu_seconds':limit,'transitions':budget['training_transitions']+budget['nontraining_transitions']}:
        raise Conflict('H1 resources must bind exact mode budget and two five-second cleanup margins')
    if spec['seed']!=config['training']['seed'] or spec['method']!=config['method']['version'] or spec['evaluation']!=config['versions']['metric'] or spec['runtime']!=config['execution']['frozen_runtime_root']:
        raise Conflict('H1 seed/method/evaluation/runtime mismatch')
    expected_product=Path(config['product']['path'])/'isaaclab-training/instinctlab/envs/unified_h1_direct_env.py'
    if spec['pins']['product']['path']!=str(expected_product) or spec['pins']['runtime']!=spec['pins']['executable']:
        raise Conflict('H1 product/runtime pin mismatch')
    if not {'status','counters','process_identity','process_start'}<=set(spec['observations']):raise Conflict('H1 required raw observations omitted')
    return observed


def environment(spec):
    config=json.loads((Path(spec['h1']['workload_root'])/'training_workloads/unified_h1/candidate_config.json').read_text())
    return {'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','CUDA_VISIBLE_DEVICES':'0',
        'PYTHONPATH':os.pathsep.join([spec['h1']['workload_root'],str(Path(config['product']['path'])/'isaaclab-training')])}


def collect(spec,directory,receipt):
    """Separate process exit, raw counters and scientific/formal conclusions."""
    output=Path(spec['h1']['attempt'])/'results'/spec['h1']['mode'];d=Path(directory)
    raw={};manifest={}
    if output.is_dir():
        for path in sorted(output.rglob('*')):
            if path.is_symlink():raise Conflict('H1 evidence symlink')
            if path.is_file():manifest[str(path.relative_to(output))]={'sha256':digest(path),'bytes':path.stat().st_size}
        for name in ['status.json','process_start.json','process_identity.json','runtime_resources.json']:
            path=output/name
            if path.exists():
                if path.stat().st_size>4*1024**2:raise Conflict('oversize H1 control evidence')
                value=json.loads(path.read_text());raw[name]=value
                saved=d/'h1-evidence'/sha(value)/name
                if not saved.exists():atomic(saved,canonical(value))
    status=raw.get('status.json',{});start=raw.get('process_start.json',{});ident=raw.get('process_identity.json',{})
    if start and start.get('authorization_sha256')!=spec['pins']['authorization']['sha256']:raise Conflict('H1 raw authorization identity mismatch')
    owned=d/'process-identity.json'
    if ident and owned.exists():
        expected=json.loads(owned.read_text())
        if ident.get('pid')!=expected['pid'] or ident.get('process_group_id',ident.get('pgid'))!=expected['pgid']:
            raise Conflict('H1 raw process identity mismatch')
    counters=status.get('counters',{});authority=json.loads((d/'h1-authority.json').read_text())
    bound=authority['authorization']['budgets']
    fields={'live_process_starts':'live_process_starts','simulator_initializations':'simulator_initializations','training_transitions':'training_transitions',
            'nontraining_transitions':'nontraining_transitions','real_optimizer_updates':'optimizer_updates','real_checkpoint_writes':'checkpoint_writes',
            'initialization_physics_ticks':'initialization_ticks','explicit_resets':'explicit_resets','automatic_resets':'automatic_resets'}
    for key,limit in fields.items():
        if key in counters and (type(counters[key]) is not int or not 0<=counters[key]<=bound[limit]):raise Conflict('H1 raw counter exceeds authority: '+key)
    complete=bool(start and ident and status.get('status') in {'PASS','FAIL','EXPECTED_CONTROLLED_FAILURE'} and all(k in counters for k in fields)
        and counters.get('attempted_policy_steps')==counters.get('completed_policy_steps') and counters.get('attempted_policy_steps') is not None)
    transitions=counters.get('training_transitions',0)+counters.get('nontraining_transitions',0)
    if complete and transitions!=counters.get('real_environment_transitions'):raise Conflict('H1 transition accounting inconsistent')
    allocated=receipt.get('allocated_seconds')
    if allocated is not None and (type(allocated) not in (int,float) or not math.isfinite(allocated) or allocated<0):raise Conflict('invalid allocation interval')
    record={'scope':'H1_RAW_EXECUTION','scientific_validity':'UNASSESSED','formal_verdict':'NOT_GRANTED','manifest':manifest,
            'counters':counters,'transitions':transitions if complete else None,'counter_completeness':'FINAL' if complete else 'INCOMPLETE',
            'allocation_gpu_seconds':receipt.get('allocated_seconds'),'allocation_basis':'allocated_device_wall_seconds',
            'exit_fact':receipt['status'],'raw_status':status.get('status')}
    path=d/'h1-collection.json'
    if path.exists():
        old=json.loads(path.read_text())
        if old.get('counter_completeness')=='FINAL' and old!=record:raise Conflict('H1 final collection drift')
    else:atomic(path,canonical(record))
    revision=d/'h1-collections'/(sha(record)+'.json')
    if not revision.exists():atomic(revision,canonical(record))
    return record
