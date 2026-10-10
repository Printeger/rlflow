"""Bounded decoding/audit of a held stdout FD; NEVER producer authority.

The original source owner must separately establish release, producer, account,
exit and EOF. This helper owns no FD and cannot settle or publish evidence.
"""
import fcntl
import hashlib
import os
import stat

from .hybrid_native_model_stream import PacketTranscript
from .hybrid_usage_stream import MAX_LINE
from .store import Conflict

READ_BYTES = 65536
READ_LINES = 128
MAX_BYTES = 1024**2


class _HeldPacketReader:
    def __init__(self, fd, *, role, candidate_sha256):
        self.fd = fd
        self.identity = None
        self.transcript = PacketTranscript(role=role, candidate_sha256=candidate_sha256)
        self.seen = None
        self.anchor = b''
        self.tail = b''
        self.audit = None
        self.result = None
        self.failed = False
        self.identity = self._stamp()[:2]

    def _stamp(self):
        info = os.fstat(self.fd)
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        if (not stat.S_ISREG(info.st_mode) or flags & os.O_ACCMODE != os.O_RDONLY or
                info.st_size > MAX_BYTES or
                self.identity is not None and (info.st_dev, info.st_ino) != self.identity):
            raise Conflict('original bounded read-only regular packet FD required')
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _check(self):
        stamp = self._stamp()
        if self.seen is not None and (stamp[2] < self.seen[2] or
                stamp[2] == self.seen[2] and stamp != self.seen):
            raise Conflict('held packet stdout changed without append')
        offset = self.transcript.offset
        if self.anchor and os.pread(self.fd, len(self.anchor), offset-len(self.anchor)) != self.anchor:
            raise Conflict('held packet prefix tip changed')
        if self.tail and os.pread(self.fd, len(self.tail), offset) != self.tail:
            raise Conflict('held packet partial tail changed')
        return stamp

    def poll(self):
        """One finite read step. Completion is decoding, not authentic EOF."""
        if self.failed:
            raise Conflict('held packet reader failed; no replacement')
        try:
            stamp = self._check()
            if self.audit is not None:
                return self._audit_step(stamp)
            offset = self.transcript.offset
            raw = os.pread(self.fd, READ_BYTES-len(self.anchor)-len(self.tail), offset)
            cursor = 0
            for _ in range(READ_LINES):
                end = raw.find(b'\n', cursor)
                if end < 0:
                    break
                line = raw[cursor:end+1]
                self.transcript.accept(offset+cursor, line)
                cursor = end+1
            remainder = raw[cursor:]
            if b'\n' not in remainder and len(remainder) > MAX_LINE:
                raise Conflict('held packet partial line exceeds bound')
            final = self._stamp()
            if final[2] < stamp[2] or final[2] == stamp[2] and final != stamp:
                raise Conflict('held packet stdout changed during read')
            self.anchor = (self.anchor+raw[:cursor])[-MAX_LINE:]
            self.tail = remainder if b'\n' not in remainder else b''
            self.seen = final
            return self._snapshot()
        except Exception:
            self.failed = True
            raise

    def finish_data(self):
        """Begin/advance full prefix audit; caller EOF assertion grants nothing."""
        if self.failed:
            raise Conflict('held packet reader failed; no replacement')
        try:
            stamp = self._check()
            if self.audit is None:
                if self.transcript.state != 'DONE' or self.tail or self.transcript.offset != stamp[2]:
                    raise Conflict('complete consumed packet data required')
                self.audit = {'stamp': stamp, 'offset': 0, 'hash': hashlib.sha256()}
            return self._audit_step(stamp)
        except Exception:
            self.failed = True
            raise

    def _audit_step(self, stamp):
        audit = self.audit
        if stamp != audit['stamp']:
            raise Conflict('held final packet data changed')
        if self.result is None:
            block = os.pread(self.fd, min(READ_BYTES, stamp[2]-audit['offset']), audit['offset'])
            if not block and audit['offset'] < stamp[2]:
                raise Conflict('held packet audit short read')
            audit['hash'].update(block)
            audit['offset'] += len(block)
            if self._stamp() != stamp:
                raise Conflict('held packet changed during audit')
            if audit['offset'] == stamp[2]:
                if audit['hash'].digest() != self.transcript.hash.digest():
                    raise Conflict('held earlier packet prefix rewritten')
                self.result = self.transcript.finish()
        return self._snapshot()

    def _snapshot(self):
        return {'offset': self.transcript.offset, 'data_complete': self.result is not None,
            'audit_offset': None if self.audit is None else self.audit['offset'],
            'source_authenticated': False, 'settlement_enabled': False,
            'condition_evidence_enabled': False}
