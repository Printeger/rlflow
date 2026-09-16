"""Run only against administrator-provisioned disposable project quota directories."""
import errno
import json
import os
from pathlib import Path
import sys
import time
from rlflow.store import Store,atomic,canonical

if len(sys.argv)!=4:raise SystemExit('usage: quota_acceptance BYTE_DIRECTORY INODE_DIRECTORY CONTROL_RECORD_DIRECTORY')
byte_root,inode_root,control=map(lambda v:Path(v).resolve(strict=True),sys.argv[1:])
if byte_root==inode_root or control.is_relative_to(byte_root) or control.is_relative_to(inode_root):raise SystemExit('separate quota projects and independent control storage required')
report={'uid':os.getuid(),'started':time.time(),'raw_files_retained':True,'real_model_calls':0,'results':[]}
for name,root in [('bytes',byte_root),('inodes',inode_root)]:
    target=root/('acceptance-'+str(time.time_ns()));target.mkdir()
    amount=0;failure=None
    try:
        if name=='bytes':
            with (target/'payload').open('xb',buffering=0) as stream:
                for _ in range(32768):
                    stream.write(b'\0'*4096);amount+=4096
        else:
            for i in range(4096):
                with (target/str(i)).open('xb'):pass
                amount+=1
    except OSError as exc:failure={'errno':exc.errno,'message':str(exc)}
    row={'kind':name,'path':str(target),'amount':amount,'failure':failure}
    report['results'].append(row);atomic(control/'quota-report.json',canonical(report))
    assert failure and failure['errno'] in (errno.EDQUOT,errno.ENOSPC),row
    store=Store(control/'controller-state')
    store.transact('QUOTA_EXHAUSTED',name,lambda s:s['historical'].update({name:row}))
    atomic(control/'controller-state/STOP',b'control survives task quota exhaustion')
    assert store.audit()==store.replay() and (control/'controller-state/STOP').exists()
report['passed']=True;atomic(control/'quota-report.json',canonical(report))
