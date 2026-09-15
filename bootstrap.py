"""Select and verify a frozen control release before importing any rlflow module."""
import hashlib
import json
import os
from pathlib import Path
import sys

source=Path(__file__).resolve().parent
state=Path.home()/'.local/share/rlflow-standalone/coordination/research'
for i,arg in enumerate(sys.argv[1:],1):
    if arg=='--state-dir' and i+1<len(sys.argv):state=Path(sys.argv[i+1]).resolve()
    elif arg.startswith('--state-dir='):state=Path(arg.split('=',1)[1]).resolve()
pointer=state/'runtime/current-release.json'
selected=source
saved=json.loads(pointer.read_text()) if pointer.exists() else None
# Read committed publication facts without importing mutable control modules.
# The pointer is an export; an interrupted export must not select an older release.
database=state/'runtime/research.db'
if database.exists():
    import sqlite3
    published={};version=0
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
        for previous,current,payload,digest in db.execute('SELECT previous_state_version,new_state_version,payload,payload_sha256 FROM events ORDER BY seq'):
            raw=json.loads(payload)
            actual=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            if previous!=version or current!=version+1 or actual!=digest:raise SystemExit('rlflow: ledger integrity failed during release selection')
            version=current
            if 'releases' in raw['set']:published=raw['set']['releases']
    rows=[(r.get('published_sequence',0),rid,r) for rid,r in published.items() if r.get('published_sequence')]
    if rows:
        _,rid,record=max(rows);saved={'id':rid,'path':record['path']}
if saved:
    selected=Path(saved['path']).resolve(strict=True)
    if not selected.is_relative_to(state.resolve()/'releases'):
        raise SystemExit('rlflow: release path escapes state release storage')
    record=json.loads((selected/'release.json').read_text())
    digest=hashlib.sha256(json.dumps(record['files'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if saved['id']!=record['id'] or digest!=saved['id']:
        raise SystemExit('rlflow: release identity mismatch')
    for name,digest in record['files'].items():
        p=(selected/name).resolve(strict=True)
        if not p.is_relative_to(selected) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise SystemExit('rlflow: frozen release source drift')
sys.path.insert(0,str(selected))
os.chdir(selected)
from rlflow.cli import main
raise SystemExit(main())
