"""Offline process fixture. No installed model CLI or network is invoked."""
import json,os,sys,time,subprocess
from pathlib import Path

if sys.argv[1]=='worker':
    sys.path.insert(0,str(Path.cwd()))
    from rlflow import worker,isolation
    request_path=sys.argv[2]
    def fixture_command(*args,**kwargs):
        request=json.loads(Path(request_path).read_text())
        if (Path(request['root'])/'fixture-pause-before-model').exists():
            from rlflow.store import Store
            from rlflow.packages import pause
            pause(Store(request['root']),request['stage_id'],True)
        return [sys.executable,str(Path(__file__).resolve()),'cli',request_path],{'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'}
    isolation.codex_command=fixture_command
    worker.run(request_path)
elif sys.argv[1]=='cli':
    r=json.loads(Path(sys.argv[2]).read_text());d=Path(r['directory'])
    with (Path(r['root'])/'cli-starts.log').open('a') as f:f.write(r['id']+'\n')
    if not (Path(r['root'])/'fixture-no-usage').exists():print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}),flush=True)
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
    (d/'fixture-descendant.json').write_text(json.dumps({'pid':child.pid}))
    (d/'fixture-cli-ready').write_text('ready')
    while not (d/'fixture-result.json').exists():time.sleep(.02)
    (d/'result.json').write_bytes((d/'fixture-result.json').read_bytes())
    child.terminate();child.wait()
