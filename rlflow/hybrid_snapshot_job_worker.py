"""Fixed finite cache-maintenance child; never creates business owners."""
import ctypes
import json
import os
import resource
import signal
import sys


def main():
    # Install the fixed profile before importing the application/dependencies.
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    signal.alarm(15)
    parent = os.getppid()
    if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) or parent != os.getppid():
        raise SystemExit(126)
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:raise SystemExit(126)
    config = json.loads(raw)
    if set(config) != {'binding', 'parent'} or config['parent'] != parent or parent != os.getppid():
        raise SystemExit(126)
    from .hybrid_snapshot_job import _physical, _head, _resources
    from .store import Store
    from .snapshot_maintenance import maintain
    record = config['binding']; _physical(record); _resources(record)
    store = Store.attach_existing(record['root'], project_id=record['project'], data_mode='fixture')
    if store.store_epoch != record['epoch']:raise SystemExit(126)
    store._existing_lock_identities = {'writer': tuple(record['files']['writer.lock']),
        'snapshot-maintenance': tuple(record['files']['snapshot-maintenance.lock'])}
    _physical(record)
    with store.read_connection() as db:
        db.execute('BEGIN'); _head(db, record)
    raise SystemExit(0 if maintain(store, _before_publish=lambda: (_physical(record), _resources(record))) else 1)
