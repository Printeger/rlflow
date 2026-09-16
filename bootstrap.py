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
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='projection_meta'").fetchone():
            version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
            if version!=db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]:
                raise SystemExit('rlflow: projection version mismatch; explicit recovery required')
            def decode(value):
                if isinstance(value,dict) and set(value) in ({'$rlflow_blob'},{'$rlflow_blob','literal'}):
                    data=db.execute('SELECT data FROM blobs WHERE digest=?',(value['$rlflow_blob'],)).fetchone()
                    if data is None or hashlib.sha256(data[0]).hexdigest()!=value['$rlflow_blob']:
                        raise SystemExit('rlflow: release blob integrity mismatch')
                    literal=value.get('literal',False);value=json.loads(data[0])
                    if literal:return value
                if isinstance(value,dict):return {k:decode(v) for k,v in value.items()}
                if isinstance(value,list):return [decode(v) for v in value]
                return value
            for rid,value in db.execute("SELECT object_key,value FROM projection WHERE section='releases' AND object_key!=''"):
                published[rid]=decode(json.loads(value))
        else:
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
