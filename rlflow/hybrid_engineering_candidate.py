"""Bounded arbitrary candidate transformation and managed CPU verification.

No writer, approval, model provenance, execution grant or evidence publisher.
The core may consume this data only after authenticating the actual Engineer
source. Original projects are never modified; executable bytes run ONLY in the
existing separately approved configured CPU scope, not in this module.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from .hybrid_goals import digest
from .hybrid_local_cpu_profile import validate_spec,validate_acceptance
from .store import Conflict, canonical

MAX_BYTES = 49152
MAX_FILES = 32


def _path(name):
    if (type(name) is not str or len(name) > 200 or
            not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name) or
            any(part in ('.', '..') or part.startswith('.') for part in name.split('/'))):
        raise Conflict('bounded non-hidden relative candidate path required')
    return name


def _text(value):
    if type(value) is not str:
        raise Conflict('candidate UTF-8 text required')
    try:
        raw = value.encode('utf-8')
    except UnicodeError as error:
        raise Conflict('candidate UTF-8 text required') from error
    if len(raw) > MAX_BYTES:
        raise Conflict('bounded candidate text required')
    return raw


def _snapshot(files):
    if type(files) is not dict or not 1 <= len(files) <= MAX_FILES:
        raise Conflict('bounded nonempty candidate snapshot required')
    total = 0
    for name, value in files.items():
        _path(name); total += len(_text(value))
        if any(parent in files for parent in _parents(name)):
            raise Conflict('candidate file/directory collision')
    if total > MAX_BYTES or len(canonical(files)) > 60000:
        raise Conflict('bounded candidate snapshot bytes required')
    return dict(files)


def _parents(name):
    parts = name.split('/')
    return ('/'.join(parts[:index]) for index in range(1, len(parts)))


def _hash(text):
    return 'sha256:' + hashlib.sha256(_text(text)).hexdigest()


@dataclass(frozen=True)
class Candidate:
    """Immutable data, NOT an authenticated model or original writer receipt."""
    base_sha256: str
    patch_sha256: str
    output_sha256: str
    raw: bytes

    def files(self):
        if type(self.raw) is not bytes or len(self.raw) > 60000:
            raise Conflict('bounded candidate serialization required')
        try:
            files = _snapshot(json.loads(self.raw))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise Conflict('valid bounded candidate serialization required') from error
        if canonical(files) != self.raw:
            raise Conflict('canonical candidate serialization required')
        if digest(files) != self.output_sha256:
            raise Conflict('candidate output bytes/hash differ')
        return files


def transform(files, patch, *, allowed_paths):
    """Closed replacement/addition/deletion protocol, no diff heuristics.

    Every original file edit names its exact before hash; a new file requires
    before=null. No commands, target filesystem paths or test criteria come
    from the patch. CAS/authority and actual source checks remain core duties.
    """
    original = _snapshot(files)
    if (type(allowed_paths) not in (tuple, list) or not 1 <= len(allowed_paths) <= MAX_FILES or
            any(type(name) is not str for name in allowed_paths) or
            len(set(allowed_paths)) != len(allowed_paths)):
        raise Conflict('exact bounded approved candidate paths required')
    for name in allowed_paths: _path(name)
    if (type(patch) is not dict or set(patch) != {'base_sha256', 'edits'} or
            patch['base_sha256'] != digest(original) or type(patch['edits']) is not list or
            not 1 <= len(patch['edits']) <= MAX_FILES):
        raise Conflict('closed patch with original base hash required')
    after = dict(original); seen = set()
    for edit in patch['edits']:
        if type(edit) is not dict or set(edit) != {'path', 'before_sha256', 'after'}:
            raise Conflict('closed candidate edit required')
        name = _path(edit['path'])
        if name not in allowed_paths or name in seen:
            raise Conflict('candidate edit outside approved paths or duplicated')
        seen.add(name)
        expected = _hash(original[name]) if name in original else None
        if edit['before_sha256'] != expected:
            raise Conflict('candidate original before hash differs')
        if edit['after'] is None:
            if name not in original: raise Conflict('cannot delete absent candidate file')
            del after[name]
        else:
            _text(edit['after']); after[name] = edit['after']
    after = _snapshot(after)
    return Candidate(digest(original), digest(patch), digest(after), canonical(after))


# These bytes are approved CPU task code. They are never executed in the core.
# A fresh isolated child runs the frozen acceptance script with the candidate
# import root. Candidate stdout/exit are observations, not independent Review
# or proof that adversarial code cannot tamper with in-process test semantics.
_VERIFY = '''import json, pathlib, subprocess, sys
payload=json.loads(pathlib.Path(WORK,'candidate.json').read_text())
root=pathlib.Path(WORK,'candidate')
root.mkdir(mode=0o700)
for name,text in payload['files'].items():
 target=root/name
 target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 with target.open('x',encoding='utf-8',newline='') as stream:stream.write(text)
script="import sys; sys.path.insert(0,"+repr(str(root))+");\\n"+payload['checks']
done=subprocess.run(['/usr/bin/python3','-I','-c',script],cwd=root,
                    stdin=subprocess.DEVNULL)
if done.returncode != 0:
 raise RuntimeError('candidate checks exited '+str(done.returncode))
'''


def verification_spec(candidate, *, checks, stdout=None, acceptance=None, seconds=10, limits=None):
    """Freeze candidate AND externally chosen checks before CPU approval.

    Changing the candidate, tests or rule requires a new spec/grant. This does
    not turn an old fixed/zero-model grant into a model execution capability.
    Output matching is machine verification only; exit status is checked by
    the existing result service. Caller must supply checks from the contract,
    never trust tests/expected output suggested in the Engineer patch.
    Supply either legacy stdout or one closed acceptance rule. JSON metrics
    and stderr policy remain exactly the externally approved criteria.
    """
    if type(candidate) is not Candidate:
        raise PermissionError('exact bounded candidate data required')
    files = candidate.files()
    raw_checks = _text(checks)
    if not raw_checks or len(raw_checks) > 8192:
        raise Conflict('bounded frozen acceptance script required')
    if acceptance is None:
        _text(stdout)
        rule={'method':'EXACT_STDOUT_UTF8','stdout':stdout,'stderr_empty':True}
    else:
        if stdout is not None:
            raise Conflict('one original CPU acceptance rule required; no stdout override')
        rule=validate_acceptance(acceptance)
    payload = canonical({'files': files, 'checks': checks,
        'candidate_binding': {'base_sha256': candidate.base_sha256,
            'patch_sha256': candidate.patch_sha256, 'output_sha256': candidate.output_sha256}}).decode('utf-8')
    return validate_spec({'purpose': 'engineering', 'code': _VERIFY,
        'inputs': {'candidate.json': payload}, 'seconds': seconds,
        'limits': {'memory_max': 67108864, 'cpu_max': '100000 100000', 'pids_max': 12}
                  if limits is None else limits,
        'acceptance': rule})
