"""Finite, gated CPU protocol-conformance participant, NEVER a model executor.

The protected runtime uses this exact program/hash, not a WorkingPlan command
rewrite. No candidate access, arbitrary command, network, model, or delegation.
"""
import ctypes
import json
import os
import resource
import select
import signal
import sys
import time

SCENARIOS = frozenset(('complete', 'missing', 'running', 'bad_ack', 'cpu_trial'))


def run(parent_pid, nonce, scenario):
    if (scenario not in SCENARIOS or parent_pid <= 0 or len(nonce) != 32 or
            any(c not in '0123456789abcdef' for c in nonce) or os.getppid() != parent_pid):
        raise SystemExit(126)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise SystemExit(126)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))
    if scenario == 'cpu_trial':
        resource.setrlimit(resource.RLIMIT_AS, (128*1024**2, 128*1024**2))
    # Identity registration and durable RELEASE_INTENT must precede this gate.
    # The unreleased child has its own finite lifetime even after a lost Popen.
    if not select.select([0], [], [], 3)[0] or os.read(0, 1) != b'G':
        raise SystemExit(126)

    def line(value):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'
        while raw:
            count = os.write(1, raw)
            if count <= 0: raise SystemExit(126)
            raw = raw[count:]

    line({'type': 'runtime.started', 'nonce': nonce if scenario != 'bad_ack' else '0' * 32,
          'pid': os.getpid(), 'program': 'FIXED_CPU_PI_TRIAL_V1' if scenario == 'cpu_trial' else 'FIXED_CPU_PROTOCOL_V1'})
    if scenario == 'cpu_trial':
        # Exact immutable numerical profile, not a caller script/argument/data.
        # Actual raw coordinates, not mocked business/usage counters.
        began_cpu, began_wall = time.process_time_ns(), time.monotonic_ns()
        counts = []
        for seed in (7, 11, 19):
            state = seed; inside = 0
            for index in range(128):
                state = (1664525*state + 1013904223) & 0xffffffff; x = state >> 16
                state = (1664525*state + 1013904223) & 0xffffffff; y = state >> 16
                hit = x*x+y*y < 65536**2; inside += hit
                line({'type': 'cpu.trial.sample', 'seed': seed, 'index': index,
                      'x': x, 'y': y, 'inside': hit})
            counts.append(inside)
        line({'type': 'cpu.trial.completed', 'inside_counts': counts,
              'cpu_ns': time.process_time_ns()-began_cpu, 'wall_ns': time.monotonic_ns()-began_wall})
        line({'type': 'fixture.end'}); os.fsync(1); return
    line({'type': 'thread.started', 'thread_id': 'fixture_parent'})
    line({'type': 'turn.started'})
    usage = {'input_tokens': 100, 'output_tokens': 10, 'cached_input_tokens': 20}
    if scenario == 'missing': del usage['output_tokens']
    line({'type': 'turn.completed', 'event_id': 'fixture_turn_1', 'usage': usage})
    os.fsync(1)
    if scenario == 'running':
        # Fixed participant creates NO descendants. Bounded liveness output lets
        # the integration prove STOP prevents further source growth, not just ACK.
        deadline = time.monotonic() + 3
        sequence = 0
        while time.monotonic() < deadline:
            if select.select([0], [], [], .02)[0]:
                os.read(0, 1); break
            sequence += 1
            line({'type': 'fixture.heartbeat', 'sequence': sequence})
    line({'type': 'fixture.end'}); os.fsync(1)


if __name__ == '__main__':
    if len(sys.argv) != 4: raise SystemExit(126)
    run(int(sys.argv[1]), sys.argv[2], sys.argv[3])
