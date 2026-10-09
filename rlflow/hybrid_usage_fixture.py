"""Fixed finite CPU usage protocol producer. NEVER a model/tool executor.

Executed only by the protected fixture source owner; no arbitrary command or
caller usage payload. Synthetic counters are not real model tokens/invoices.
"""
import ctypes
import json
import os
import resource
import select
import signal
import sys
import time

SCENARIOS = frozenset(('cumulative', 'per_turn', 'parent_inclusive', 'partial',
                       'missing', 'failed', 'overlong', 'linger', 'history', 'invalid_id'))


def run(parent_pid, scenario):
    if scenario not in SCENARIOS or parent_pid <= 0: raise SystemExit(126)
    if os.getppid() != parent_pid: raise SystemExit(126)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise SystemExit(126)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))
    # Hold before producing anything; the original parent captures actual
    # identity/pidfd first. Timeout/death never starts a second producer.
    if not select.select([0], [], [], 3)[0] or os.read(0, 1) != b'R': raise SystemExit(126)
    def line(event):
        raw = json.dumps(event, sort_keys=True, separators=(',', ':')).encode() + b'\n'
        while raw:
            written = os.write(1, raw)
            if written <= 0: raise SystemExit(126)
            raw = raw[written:]
    def thread(name): line({'type': 'thread.started', 'thread_id': name})
    def started(): line({'type': 'turn.started'})
    def completed(event_id, input_=100, output=10, cached=20):
        usage = {'input_tokens': input_, 'output_tokens': output, 'cached_input_tokens': cached}
        if scenario == 'missing': del usage['output_tokens']
        line({'type': 'turn.completed', 'event_id': event_id, 'usage': usage})
    if scenario == 'history':
        for _ in range(384):
            line({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'fixed padding ' + 'x' * 500}})
    thread('fixture_parent'); started(); completed('fixture_turn_1')
    if scenario == 'per_turn':
        completed('fixture_turn_1')  # Same stable identity, different original position.
        started(); completed('fixture_turn_2')
    elif scenario == 'parent_inclusive':
        started(); completed('fixture_turn_2', 300, 30, 60)
        thread('fixture_child'); started(); completed('fixture_child_turn', 150, 15, 30)
    elif scenario == 'partial':
        started()
        raw = b'{"event_id":"fixture_turn_2","type":"turn.completed","usage":{"input_tokens":200'
        os.write(1, raw); os.fsync(1)
        # Parent requests completion only after actually observing partial tail.
        if not select.select([0], [], [], 3)[0] or os.read(0, 1) != b'C': raise SystemExit(126)
        os.write(1, b',"output_tokens":20,"cached_input_tokens":40}}\n')
    elif scenario == 'failed':
        line({'type': 'turn.failed', 'error': {'message': 'fixed fixture failure'}})
        os.fsync(1); raise SystemExit(1)
    elif scenario == 'overlong':
        os.write(1, b'{' + b'x' * 16384 + b'\n')
    elif scenario == 'invalid_id':
        started(); completed('\ud800', 200, 20, 40)
    elif scenario == 'linger':
        # Finite independent watchdog; no model, child process or tooling.
        select.select([0], [], [], 3)
    elif scenario == 'cumulative':
        started(); completed('fixture_turn_2', 300, 30, 60)
    line({'type': 'fixture.end'}); os.fsync(1)


if __name__ == '__main__':
    if len(sys.argv) != 3: raise SystemExit(126)
    run(int(sys.argv[1]), sys.argv[2])
