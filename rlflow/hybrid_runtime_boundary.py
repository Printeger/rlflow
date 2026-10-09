"""Cold-process legacy deny boundary; no execution capability is issued.

The mandatory release-local policy is the trust root, not caller request.root.
Missing or damaged BOUND material denies ALL new starts. Protected scopes are
permanent reserved paths plus physical ancestors, not a renewable controller
lease. This is cooperative entry fencing, not an OS sandbox against same-UID
code replacement or an already-running older release.

Standalone loading supports isolation.py/jobs.py's isolated file entry points.
No Store/jobs imports: the guard must run before resource or process side effects.
"""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat


class BoundaryDenied(PermissionError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def policy_source(descriptor):
    """Deterministic literal release-local policy bytes, NOT a mode grant.

    Pure sealing and the protected installer must use the SAME generator. It
    emits no caller code or imports, and is never accepted as a live capability.
    """
    literal = repr(json.loads(_canonical(descriptor)))
    return ('"""Generated fixed installation policy; no request-selected mode."""\n'
            'DESCRIPTOR = ' + literal + '\n').encode('utf-8')


def _path(value):
    if not isinstance(value, (str, Path)):
        raise BoundaryDenied('concrete boundary path required')
    path = Path(value)
    if (not path.is_absolute() or '..' in path.parts or '\x00' in str(path) or
            len(path.parts) > 64 or len(str(path).encode()) > 4096):
        raise BoundaryDenied('bounded absolute boundary path required')
    return path


def _identity(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise BoundaryDenied('boundary ancestor is not a directory')
    with open('/proc/self/fdinfo/' + str(fd), encoding='ascii') as stream:
        raw = stream.read(8193)
    rows = [line.split(':', 1)[1].strip() for line in raw.splitlines() if line.startswith('mnt_id:')]
    if len(raw) > 8192 or len(rows) != 1 or not rows[0].isdigit():
        raise BoundaryDenied('boundary mount identity unavailable')
    mount_id = int(rows[0])
    # A subtree bind can conceal a protected ancestor. Do not infer alias
    # disjointness on such a mount, or on unsupported network/overlay storage.
    with open('/proc/self/mountinfo', encoding='utf-8') as stream:
        mounts = stream.read(4 * 1024**2 + 1)
    if len(mounts) > 4 * 1024**2:
        raise BoundaryDenied('boundary mount metadata exceeds bound')
    matches = []
    for line in mounts.splitlines():
        prefix, separator, suffix = line.partition(' - ')
        fields = prefix.split()
        if fields and fields[0] == str(mount_id):
            tail = suffix.split()
            if (not separator or len(fields) < 6 or len(tail) < 3 or fields[3] != '/' or
                    tail[0] not in {'ext4', 'xfs', 'btrfs', 'tmpfs'}):
                raise BoundaryDenied('direct supported local boundary filesystem required')
            matches.append(tail[0])
    if len(matches) != 1:
        raise BoundaryDenied('boundary mount unavailable')
    return [info.st_dev, info.st_ino, mount_id]


@contextmanager
def _held_chain(path):
    """Keep original ancestor dirfds through dependent relative-file reads."""
    path = _path(path)
    descriptors = []
    try:
        try:
            descriptors.append(os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC))
            chain = [_identity(descriptors[-1])]
            for part in path.parts[1:]:
                descriptors.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                           dir_fd=descriptors[-1]))
                chain.append(_identity(descriptors[-1]))
        except BoundaryDenied:
            raise
        except OSError as error:
            raise BoundaryDenied('boundary physical chain unavailable') from error
        # The dependent operation's failure (including a durable COMMIT lost
        # return) is not evidence of a path failure. Preserve its identity.
        yield descriptors, chain
    finally:
        errors = []
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError as error:
                errors.append(error)
        if errors:
            raise BoundaryDenied('boundary descriptor cleanup failed') from errors[0]


def directory_chain(path):
    """NOFOLLOW physical chain, usable by protected installation construction."""
    with _held_chain(path) as (_, chain):
        return chain


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)


def _chain_value(value, path):
    if (type(value) is not list or len(value) != len(path.parts) or
            any(type(row) is not list or len(row) != 3 or
                any(type(number) is not int or not 0 <= number < 2**64 for number in row)
                for row in value)):
        raise BoundaryDenied('closed actual-integer physical chain required')


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise BoundaryDenied('duplicate boundary catalog key')
        result[key] = value
    return result


def _policy():
    # Never import from sys.path/HOME/CWD/env or a caller-supplied release.
    path = Path(__file__).resolve().with_name('runtime_boundary_policy.py')
    if path.is_symlink() or not path.is_file():
        raise BoundaryDenied('mandatory installation policy unavailable')
    # Execute original bounded release-local source, not a timestamp-based .pyc
    # cache that could survive descriptor generation with the same mtime/size.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 65536:
            raise BoundaryDenied('bounded mandatory policy source required')
        raw = os.read(fd, 65537)
        if (len(raw) != info.st_size or os.read(fd, 1) or _stamp(os.fstat(fd)) != _stamp(info) or
                _stamp(os.stat(path, follow_symlinks=False)) != _stamp(info)):
            raise BoundaryDenied('mandatory policy source changed')
    finally:
        os.close(fd)
    namespace = {'__file__': str(path), '__name__': '_rlflow_fixed_boundary_policy'}
    exec(compile(raw, str(path), 'exec'), namespace)
    return namespace['DESCRIPTOR']


def _catalog(descriptor):
    if type(descriptor) is not dict or descriptor.get('version') != 1 or type(descriptor.get('version')) is not int:
        raise BoundaryDenied('unknown installation boundary descriptor')
    if descriptor == {'version': 1, 'mode': 'LEGACY_UNBOUND'}:
        return None
    if (set(descriptor) != {'version', 'mode', 'catalog_path', 'catalog_sha256', 'catalog_parent_chain', 'catalog_identity'} or
            descriptor['mode'] != 'BOUND_HYBRID_NONEXECUTING' or
            not isinstance(descriptor['catalog_sha256'], str) or
            re.fullmatch('[0-9a-f]{64}', descriptor['catalog_sha256']) is None):
        raise BoundaryDenied('closed BOUND installation descriptor required')
    path = _path(descriptor['catalog_path'])
    _chain_value(descriptor['catalog_parent_chain'], path.parent)
    file_identity = descriptor['catalog_identity']
    if (type(file_identity) is not list or len(file_identity) != 2 or
            any(type(number) is not int or not 0 <= number < 2**64 for number in file_identity)):
        raise BoundaryDenied('original catalog integer identity required')
    with _held_chain(path.parent) as (parents, chain):
        if chain != descriptor['catalog_parent_chain']:
            raise BoundaryDenied('installation catalog parent rebound')
        parent = os.fstat(parents[-1])
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise BoundaryDenied('private installation catalog parent required')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parents[-1])
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or
                    info.st_nlink != 1 or not 0 < info.st_size <= 65536 or
                    [info.st_dev, info.st_ino] != file_identity):
                raise BoundaryDenied('private bounded installation catalog required')
            raw = os.read(fd, 65537)
            if (len(raw) != info.st_size or os.read(fd, 1) or
                    hashlib.sha256(raw).hexdigest() != descriptor['catalog_sha256'] or
                    _stamp(os.fstat(fd)) != _stamp(info) or
                    _stamp(os.stat(path.name, dir_fd=parents[-1], follow_symlinks=False)) != _stamp(info)):
                raise BoundaryDenied('original installation catalog bytes differ')
            if directory_chain(path.parent) != chain or _stamp(os.fstat(parents[-1])) != _stamp(parent):
                raise BoundaryDenied('installation catalog parent changed during read')
            value = json.loads(raw, object_pairs_hook=_pairs)
            if _canonical(value) != raw:
                raise BoundaryDenied('canonical installation catalog required')
        finally:
            os.close(fd)
    fields = {'version', 'mode', 'scopes', 'execution_enabled', 'release_enabled'}
    if (type(value) is not dict or set(value) not in (fields, fields | {'installation_ref'}) or
            type(value['version']) is not int or value['version'] != 1 or
            value['mode'] != 'HYBRID_LEGACY_DENIED' or value['execution_enabled'] is not False or
            value['release_enabled'] is not False or type(value['scopes']) is not list or
            not 1 <= len(value['scopes']) <= 16):
        raise BoundaryDenied('closed nonexecuting installation catalog required')
    if 'installation_ref' in value:
        ref = value['installation_ref']
        if (type(ref) is not dict or set(ref) != {'intent_key', 'accepted_state_version'} or
                not isinstance(ref['intent_key'], str) or
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', ref['intent_key']) is None or
                type(ref['accepted_state_version']) is not int or not 1 <= ref['accepted_state_version'] < 2**63):
            raise BoundaryDenied('closed original installation source reference required')
        # This guard STILL grants nothing. A future actual bootstrap owner must
        # prove the referenced core source; cold BOUND remains unconditional deny.
    roots = []
    for scope in value['scopes']:
        if type(scope) is not dict or set(scope) != {'reserved_path', 'directory_chain'}:
            raise BoundaryDenied('closed reserved installation scope required')
        root = _path(scope['reserved_path'])
        _chain_value(scope['directory_chain'], root)
        if len(root.parts) < 3 or root in roots or directory_chain(root) != scope['directory_chain']:
            raise BoundaryDenied('original reserved installation scope rebound')
        roots.append(root)
    return value


def check_legacy(*paths):
    """Reject protected paths before ANY legacy launch/resource/write intent.

Arguments identify affected scopes only; they cannot configure mode or grant
permission. BOUND requires at least one concrete affected path. Recheck this
guard at the final launch/release boundary; it is not a durable permit token.
"""
    try:
        catalog = _catalog(_policy())
        if catalog is None:
            return
        if not 1 <= len(paths) <= 128:
            raise BoundaryDenied('BOUND legacy entry requires affected scopes')
        for value in paths:
            path = _path(value)
            for scope in catalog['scopes']:
                root = Path(scope['reserved_path'])
                if path == root or root in path.parents or path in root.parents:
                    raise BoundaryDenied('Hybrid reserved scope denies legacy execution')
            # Preserve lexical tombstones above even if the reserved path is
            # gone. Resolve aliases only for additional physical exclusion.
            resolved = path.resolve(strict=False)
            while not resolved.is_dir():
                if resolved == resolved.parent:
                    raise BoundaryDenied('affected boundary ancestor unavailable')
                resolved = resolved.parent
            chain = directory_chain(resolved)
            for scope in catalog['scopes']:
                protected = scope['directory_chain']
                if (protected[-1][:2] in [item[:2] for item in chain] or
                        chain[-1][:2] in [item[:2] for item in protected]):
                    raise BoundaryDenied('Hybrid physical alias denies legacy execution')
    except BoundaryDenied:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, RuntimeError, SyntaxError) as error:
        raise BoundaryDenied('installation boundary unavailable; no legacy fallback') from error


def check_request(request, *extra_paths):
    """Known affected path fields, never JSON permission or a mode selector."""
    paths = list(extra_paths)
    stack = [(request, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 4 or len(paths) > 128:
            raise BoundaryDenied('affected request scopes exceed bound')
        if not isinstance(item, dict):
            continue
        for name in ('root', 'directory', 'candidate', 'repo', 'scratch', 'cwd', 'audit', 'output',
                     'guard_directory', 'control_root', 'tool_launch_directory'):
            if item.get(name) is not None:
                paths.append(item[name])
        for name in ('read', 'write', 'execute', 'read_extra', 'write_roots', 'execute_extra'):
            if item.get(name) is not None:
                if not isinstance(item[name], list):
                    raise BoundaryDenied('affected path array required')
                paths.extend(item[name])
        for name in ('spec', 'resources', 'task_resources', 'compute', 'cpu_runtime'):
            if item.get(name) is not None:
                stack.append((item[name], depth + 1))
        disk = item.get('disk')
        if isinstance(disk, dict):
            paths.extend(disk[name] for name in ('root', 'raw', 'path') if disk.get(name) is not None)
    if len(paths) > 128:
        raise BoundaryDenied('affected request scopes exceed bound')
    check_legacy(*paths)


def check_cold_entry():
    """A BOUND raw child cannot prove a parent's issued execution capability.

No JSON paths/argv/identity/boot string can select a disjoint legacy exception.
Only explicit UNBOUND installations retain old cold-process behavior. Check
before reading an untrusted request, loading a dispatcher or allocating state.
"""
    try:
        if _catalog(_policy()) is not None:
            raise BoundaryDenied('BOUND installation denies raw legacy child execution')
    except BoundaryDenied:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, RuntimeError, SyntaxError) as error:
        raise BoundaryDenied('installation boundary unavailable; no cold legacy fallback') from error
