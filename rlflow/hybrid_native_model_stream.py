"""Finite packet-only CLI decoding; data, never source/settlement authority.

The future original FD owner must supply contiguous lines and authenticate
producer, account, packet and EOF. Calling this decoder with fabricated bytes
does NOT create a model receipt, independent Review or ConditionEvidence.
Protocol: one thread, one turn, no tools, one final structured agent message.
Official format: https://learn.chatgpt.com/docs/non-interactive-mode
"""
import hashlib
import json

from .hybrid_engineering_candidate import transform
from .hybrid_protocol import HASH, obj, enum, validate_schema
from .hybrid_usage_stream import Accumulator, MAX_LINE, parse_line
from .store import Conflict, canonical

REVIEW = obj({'candidate_sha256': HASH, 'verdict': enum('ACCEPT', 'REVISE'),
    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
    'findings': {'type': 'array', 'maxItems': 32, 'items': obj({
        'severity': enum('MUST', 'COMMENT'),
        'text': {'type': 'string', 'minLength': 1, 'maxLength': 4000}})}})


def review_data(value, candidate_sha256):
    """Candidate-bound review DATA, never an independence/acceptance cap."""
    validate_schema(REVIEW,value)
    if value['candidate_sha256'] != candidate_sha256:
        raise Conflict('Evaluator packet candidate version differs')
    if value['verdict']=='ACCEPT' and any(row['severity']=='MUST' for row in value['findings']):
        raise Conflict('Evaluator acceptance contradicts unresolved MUST')
    # A fresh closed-data copy, not the decoder's mutable message or caller map.
    return json.loads(canonical(value))


class PacketTranscript:
    def __init__(self, *, role, candidate_sha256):
        if role not in ('Engineer', 'Evaluator'):
            raise Conflict('closed packet role required')
        validate_schema(HASH, candidate_sha256)
        self.role = role; self.candidate_sha256 = candidate_sha256
        self.offset = 0; self.lines = 0; self.state = 'EMPTY'
        self.failed = False; self.sealed = False; self.message = None
        self.failure_event = None
        self.hash = hashlib.sha256(); self.usage = Accumulator('per_turn')

    def accept(self, offset, raw):
        if self.failed or self.sealed:
            raise Conflict('packet transcript closed; no replacement')
        try:
            if type(offset) is not int or offset != self.offset or self.lines >= 4096:
                raise Conflict('contiguous bounded original packet positions required')
            event = parse_line(raw); kind = event['type']
            if self.offset + len(raw) > 1024**2:
                raise Conflict('bounded packet transcript bytes required')
            if kind == 'thread.started' and self.state == 'EMPTY':
                self.state = 'THREAD'
            elif kind == 'turn.started' and self.state == 'THREAD':
                self.state = 'TURN'
            elif kind in ('item.started', 'item.updated', 'item.completed') and self.state == 'TURN':
                item = event.get('item')
                if type(item) is not dict or item.get('type') not in ('reasoning', 'agent_message'):
                    raise Conflict('packet-only model emitted tool or unsupported item')
                if kind == 'item.completed' and item['type'] == 'agent_message':
                    if self.message is not None or type(item.get('text')) is not str:
                        raise Conflict('one final packet message required')
                    # Reuse bounded duplicate-key/depth/nonfinite checks. The
                    # artificial wrapper is decoding only, NOT a usage event.
                    encoded = item['text'].encode('utf-8')
                    wrapper = b'{"type":"packet","value":' + encoded + b'}\n'
                    if len(wrapper) > MAX_LINE:
                        raise Conflict('bounded structured packet message required')
                    decoded = parse_line(wrapper)
                    if set(decoded) != {'type', 'value'}:
                        raise Conflict('one structured packet object required')
                    value = decoded['value']
                    if type(value) is not dict:
                        raise Conflict('structured packet object required')
                    self.message = canonical(value)
                    self.state = 'MESSAGE'
            elif kind == 'turn.completed' and self.state == 'MESSAGE':
                self.state = 'DONE'
            elif (kind == 'turn.failed' and self.state in ('TURN','MESSAGE') or
                    kind == 'error' and self.state in ('EMPTY','THREAD','TURN','MESSAGE')):
                # Failure observation, not proof of final producer exit/EOF.
                # Do not interpret optional failure payload as complete usage.
                self.failure_event={'type':kind,
                    'sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}
                self.state='FAILURE_OBSERVED'
            else:
                raise Conflict('single successful packet turn lineage required')
            self.usage.accept('original_stdout', offset, raw, _parsed=event)
            self.hash.update(raw); self.offset += len(raw); self.lines += 1
        except Exception:
            self.failed = True
            raise

    def finish(self):
        """Freeze a data boundary; NOT proof of exit, STOP or original EOF."""
        if self.failed or self.state not in ('DONE','FAILURE_OBSERVED'):
            self.failed = True
            raise Conflict('complete bounded packet observation required')
        self.sealed = True
        result={'output_sha256': None if self.message is None else
                    'sha256:' + hashlib.sha256(self.message).hexdigest(),
            'stream_sha256': 'sha256:' + self.hash.hexdigest(), 'bytes': self.offset,
            'usage': self.usage.totals(), 'source_authenticated': False,
            'settlement_enabled': False, 'condition_evidence_enabled': False}
        if self.failure_event is not None:result['failure_event']=dict(self.failure_event)
        return result

    def candidate(self, files, *, allowed_paths):
        if (self.role != 'Engineer' or not self.sealed or self.failed or
                self.state!='DONE' or self.failure_event is not None):
            raise Conflict('sealed Engineer packet required')
        from .hybrid_goals import digest
        if digest(files) != self.candidate_sha256:
            raise Conflict('Engineer packet original snapshot differs')
        return transform(files, json.loads(self.message), allowed_paths=allowed_paths)

    def review(self):
        if (self.role != 'Evaluator' or not self.sealed or self.failed or
                self.state!='DONE' or self.failure_event is not None):
            raise Conflict('sealed Evaluator packet required')
        return review_data(json.loads(self.message),self.candidate_sha256)
