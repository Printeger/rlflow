"""Durable CPU-only fake jobs. Control plane owns reservations and event accounting.

submit(root, job_id, spec, stop_paths=()) is idempotent for identical inputs.
status reads persisted evidence; reconcile checks identity without starting/refunding.
All states retain start intent. RECONCILE requires investigation, never resubmission.
"""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
import uuid

CANONICAL_STOP = Path.home()/'.local/share/rlflow-standalone/coordination/commander/STOP'
TERMINAL = {'SUCCEEDED', 'FAILED', 'STOPPED', 'HANDSHAKE_TIMEOUT'}
_CHILDREN = []


def _dump(path, value):
    tmp = path.with_suffix('.tmp.' + str(os.getpid()))
    with tmp.open('w') as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path):
    return json.loads(path.read_text())


@contextlib.contextmanager
def _lock(path):
    with (path / 'lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _directory(root, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', job_id):
        raise ValueError('invalid job_id')
    return Path(root).resolve() / 'jobs' / job_id


def identity(pid):
    """Linux process identity, including PID reuse and process group protection."""
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'pgid': int(fields[2]), 'starttime': fields[19],
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def owns(record):
    return bool(record and record == identity(record['pid']))


def _kill_owned(record):
    if owns(record) and record['pid'] == record['pgid']:
        try:
            os.killpg(record['pgid'], signal.SIGKILL)
        except ProcessLookupError:
            pass
        return True
    return False


def _stopped(state):
    return any(Path(p).exists() for p in state['stop_paths'])


def _validate(spec):
    if not isinstance(spec, dict) or spec.get('backend', 'fake') != 'fake':
        raise ValueError('only CPU fake backend is enabled')
    allowed = {'backend', 'duration', 'handshake_timeout', 'mode', 'before_release_delay'}
    if set(spec) - allowed:
        raise ValueError('unknown fake job fields; arbitrary commands prohibited')
    result = {'backend': 'fake', 'duration': .05, 'handshake_timeout': 2.,
              'mode': 'normal', 'before_release_delay': 0., **spec}
    if result['mode'] not in {'normal', 'no_message', 'short_lived', 'partial_message', 'fail'}:
        raise ValueError('invalid fake mode')
    for key in ('duration', 'handshake_timeout', 'before_release_delay'):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 60:
            raise ValueError('fake timing must be finite and within 0..60 seconds')
    if result['handshake_timeout'] == 0:
        raise ValueError('handshake_timeout must be positive')
    return result


def submit(root, job_id, spec, stop_paths=()):
    spec = _validate(spec)
    path = _directory(root, job_id)
    path.mkdir(parents=True, exist_ok=True)
    stops = sorted({str(CANONICAL_STOP), *(str(Path(p).absolute()) for p in stop_paths)})
    digest = hashlib.sha256(json.dumps([spec, stops], sort_keys=True).encode()).hexdigest()
    with _lock(path):
        if (path / 'state.json').exists():
            old = _read(path / 'state.json')
            if old['spec_hash'] != digest:
                raise ValueError('job_id already binds different content')
            return old
        state = {'job_id': job_id, 'nonce': uuid.uuid4().hex, 'state': 'START_INTENT',
                 'spec': spec, 'spec_hash': digest, 'stop_paths': stops, 'created': time.time(),
                 'released': False, 'start_attempts': 1}
        if _stopped(state):
            state.update(state='STOPPED', reason='STOP before dispatch', start_attempts=0)
        _dump(path / 'state.json', state)
        if state['state'] == 'STOPPED':
            return state
        try:
            with (path / 'supervisor.log').open('ab') as log:
                proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                    '_supervise', str(path)], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True, close_fds=True)
            _CHILDREN.append(proc)
            state['supervisor'] = identity(proc.pid)
            _dump(path / 'state.json', state)
        except Exception as exc:
            state.update(state='RECONCILE', reason=f'start outcome uncertain: {type(exc).__name__}')
            _dump(path / 'state.json', state)
        return state


def status(root, job_id):
    return _read(_directory(root, job_id) / 'state.json')


def reconcile(root, job_id):
    path = _directory(root, job_id)
    with _lock(path):
        state = _read(path / 'state.json')
        if state['state'] not in TERMINAL and not owns(state.get('supervisor')):
            artifact = 'absent'
            if (path / 'result.json').exists():
                try:
                    result = _read(path / 'result.json')
                    artifact = ('identity_matches' if result.get('nonce') == state.get('nonce')
                                and result.get('job_id') == job_id else 'identity_mismatch')
                except (ValueError, AttributeError):
                    artifact = 'invalid'
            state.update(state='RECONCILE', reason='supervisor identity missing or no longer alive; no restart/refund',
                         reconciliation={'child_alive_and_owned': owns(state.get('child')),
                                         'result_artifact': artifact,
                                         'exit_evidence_available': 'exit_code' in state})
            _dump(path / 'state.json', state)
        return state


def _save(path, **changes):
    with _lock(path):
        state = _read(path / 'state.json')
        state.update(changes)
        _dump(path / 'state.json', state)
        return state


def _supervise(path):
    with _lock(path):
        state = _read(path / 'state.json')
        if state['state'] != 'START_INTENT' or state.get('supervisor') != identity(os.getpid()):
            return
    if _stopped(state):
        _save(path, state='STOPPED', reason='STOP before child dispatch')
        return
    ready_r, ready_w = os.pipe()
    release_r, release_w = os.pipe()
    proc = None
    child_id = None
    try:
        argv = [sys.executable, str(Path(__file__).resolve()), '_child', str(path), str(ready_w), str(release_r)]
        with (path / 'stdout.log').open('ab') as out, (path / 'stderr.log').open('ab') as err:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    pass_fds=(ready_w, release_r), start_new_session=True)
        os.close(ready_w); ready_w = -1
        os.close(release_r); release_r = -1
        child_id = identity(proc.pid)
        _save(path, state='HANDSHAKE', child=child_id, argv=argv)
        deadline = time.monotonic() + state['spec']['handshake_timeout']
        message = b''
        outcome = None
        while time.monotonic() < deadline:
            if _stopped(state):
                outcome = ('STOPPED', 'STOP during handshake'); break
            if proc.poll() is not None:
                outcome = ('FAILED', 'child exited before ready'); break
            readable, _, _ = select.select([ready_r], [], [], min(.02, max(0, deadline-time.monotonic())))
            if readable:
                chunk = os.read(ready_r, 128)
                if not chunk:
                    outcome = ('FAILED', 'ready pipe closed'); break
                message += chunk
                if message == b'READY\n':
                    break
                if len(message) >= 128:
                    outcome = ('FAILED', 'invalid handshake'); break
        if message != b'READY\n' and outcome is None:
            outcome = ('HANDSHAKE_TIMEOUT', 'bounded ready deadline expired')
        if outcome is None:
            _save(path, state='HELD')
            end = time.monotonic() + state['spec']['before_release_delay']
            while time.monotonic() < end and not _stopped(state):
                time.sleep(.01)
            if _stopped(state):
                outcome = ('STOPPED', 'STOP before release')
            elif not owns(child_id):
                outcome = ('FAILED', 'held child identity lost')
        if outcome:
            _kill_owned(child_id)
            proc.wait(timeout=3)
            _save(path, state=outcome[0], reason=outcome[1], exit_code=proc.returncode)
            return
        # Persist release intent before opening the gate; an interrupted write is never retried.
        _save(path, state='RELEASE_INTENT')
        if _stopped(state):
            _kill_owned(child_id); proc.wait(timeout=3)
            _save(path, state='STOPPED', reason='STOP at final gate', exit_code=proc.returncode)
            return
        os.write(release_w, b'GO\n')
        _save(path, state='RUNNING', released=True)
        while proc.poll() is None:
            if _stopped(state):
                _kill_owned(child_id); proc.wait(timeout=3)
                _save(path, state='STOPPED', reason='STOP while running', exit_code=proc.returncode)
                return
            time.sleep(.01)
        _save(path, state='SUCCEEDED' if proc.returncode == 0 else 'FAILED', exit_code=proc.returncode,
              finished=time.time())
    except BaseException as exc:
        _kill_owned(child_id)
        if proc:
            proc.wait(timeout=3)
        _save(path, state='RECONCILE', reason=f'supervision interrupted: {type(exc).__name__}')
    finally:
        for fd in (ready_r, ready_w, release_r, release_w):
            if fd >= 0:
                os.close(fd)


def _child(path, ready_w, release_r):
    state = _read(path / 'state.json')
    spec = state['spec']
    if spec['mode'] == 'short_lived':
        return 7
    if spec['mode'] == 'partial_message':
        os.write(ready_w, b'REA')
    elif spec['mode'] != 'no_message':
        os.write(ready_w, b'READY\n')
    readable, _, _ = select.select([release_r], [], [], spec['handshake_timeout'] + spec['before_release_delay'] + 2)
    if not readable or os.read(release_r, 32) != b'GO\n':
        return 8
    time.sleep(spec['duration'])
    result = {'job_id': state['job_id'], 'nonce': state['nonce'], 'backend': 'fake',
              'message': 'CPU fake workload completed', 'success': spec['mode'] != 'fail'}
    _dump(path / 'result.json', result)
    print(json.dumps(result), flush=True)
    return 9 if spec['mode'] == 'fail' else 0


if __name__ == '__main__':
    if sys.argv[1] == '_supervise':
        _supervise(Path(sys.argv[2]))
    elif sys.argv[1] == '_child':
        raise SystemExit(_child(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])))
