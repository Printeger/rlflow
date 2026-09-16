"""Enter a delegated controller subgroup before starting the dispatcher."""
import json
import os
from pathlib import Path
import sys
from .resources import membership
from .store import Conflict,atomic,canonical


def prepare(state_root):
    current=membership(os.getpid())
    root=current.parent if current.name=='control' else current
    if not {'cpu','memory','pids'}<=set((root/'cgroup.controllers').read_text().split()):
        raise Conflict('user service did not delegate CPU/memory/PID controllers')
    control=root/'control';control.mkdir(exist_ok=True)
    if current!=control:
        if set((root/'cgroup.procs').read_text().split())-{str(os.getpid())}:
            raise Conflict('delegated root has unrelated internal processes')
        (control/'cgroup.procs').write_text(str(os.getpid()))
    (root/'cgroup.subtree_control').write_text('+cpu +memory +pids')
    if membership(os.getpid())!=control:raise Conflict('controller subgroup entry failed')
    path=Path(state_root).resolve()/'runtime/resource-config.json'
    config=json.loads(path.read_text()) if path.exists() else {}
    configured=config.get('delegated_root')
    if configured and Path(configured)!=root:raise Conflict('delegated service differs from configured resource authority')
    config['delegated_root']=str(root);atomic(path,canonical(config))
    return config


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: python -m rlflow.resource_service STATE_DIRECTORY')
    prepare(sys.argv[1])
    from .engine import daemon
    daemon(sys.argv[1])
