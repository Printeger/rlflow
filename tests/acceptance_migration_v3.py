"""Read-only backup of a live ledger; migration and audit run exclusively on its copy."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from rlflow.store import Store,canonical,sha,initial

source=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve()
(root/'runtime').mkdir(parents=True,exist_ok=False)
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(root/'runtime/research.db') as dst:src.backup(dst)
started=time.monotonic();before=initial();digest=hashlib.sha256();count=0;payload_bytes=0
with sqlite3.connect(root/'runtime/research.db') as db:
    db.row_factory=sqlite3.Row
    for row in db.execute('SELECT * FROM events ORDER BY seq'):
        row=dict(row);digest.update(canonical(row));payload=json.loads(row['payload'])
        assert sha(payload)==row['payload_sha256'] and row['previous_state_version']==before['version']
        assert 'set' in payload,'fixture expects exclusively legacy source events'
        before.update(payload['set']);before['version']=row['new_state_version'];count+=1;payload_bytes+=len(row['payload'].encode())
legacy_digest=digest.hexdigest();approval_digest=sha(before['approvals'])
store=Store(root);migrated=store.replay();audited=store.audit();assert migrated==before==audited
with store.connect() as db:
    digest=hashlib.sha256()
    for row in db.execute('SELECT * FROM events ORDER BY seq'):digest.update(canonical(dict(row)))
assert digest.hexdigest()==legacy_digest
store.snapshot();assert store.recover()==before
report={'source':str(source),'copy':str(store.db),'events':count,'payload_bytes':payload_bytes,
        'legacy_event_bytes_sha256':legacy_digest,'after_event_bytes_sha256':digest.hexdigest(),
        'approvals_sha256':approval_digest,'paused':before['paused'],'enabled':before['enabled'],
        'state_equal':True,'recovery_equal':True,'elapsed_seconds':time.monotonic()-started,
        'budget_sha256':sha({k:{f:v.get(f) for f in ('budget','used_calls','used_seconds','reserved_calls','reserved_seconds','used_fake_starts','compute')} for k,v in before['stages'].items()})}
(root/'migration-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
