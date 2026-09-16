"""Bounded-memory content verification with descriptor-relative path checks."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from .store import Conflict, sha

BUFFER_SIZE = 1024 * 1024


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def stream_digest(path, *, root=None):
    path=Path(path).absolute()
    root=Path(root).absolute() if root is not None else Path(path.anchor)
    try: relative=path.relative_to(root)
    except ValueError as exc: raise Conflict('file escapes approved root') from exc
    if not relative.parts or '..' in relative.parts: raise Conflict('invalid file path')
    descriptors=[]
    try:
        # Walk from / so no ancestor symlink is silently followed.
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY);descriptors.append(fd)
        for part in path.parts[1:-1]:
            fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            descriptors.append(fd)
        source=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        descriptors.append(source)
        before=os.fstat(source)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:
            raise Conflict('file is not a private regular file')
        digest=hashlib.sha256()
        while chunk:=os.read(source,BUFFER_SIZE): digest.update(chunk)
        after=os.fstat(source)
        current=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
        if stamp(before)!=stamp(after) or stamp(after)!=stamp(current):
            raise Conflict('file changed during hashing')
        # Re-resolve the path after reading to reject replaced ancestors.
        if path.resolve(strict=True)!=path or stamp(path.stat())!=stamp(after):
            raise Conflict('file path changed during hashing')
        return digest.hexdigest()
    except OSError as exc:
        raise Conflict('cannot verify source path: '+str(path)) from exc
    finally:
        for fd in reversed(descriptors):os.close(fd)


def relative_name(name):
    if not isinstance(name,str) or not name or '\\' in name:
        raise Conflict('invalid manifest path')
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or p.as_posix()!=name or name=='.':
        raise Conflict('invalid manifest path')
    return name


def within(name, roots):
    return any(root=='.' or name==root or name.startswith(root+'/') for root in roots)


def validate_inputs(contract, module_roots, protected_paths):
    if not isinstance(contract,dict) or set(contract)!={'source_files','data_references','output_directories','environment'}:
        raise Conflict('inputs require source, data, output and environment manifests')
    names=contract['source_files'];outputs=contract['output_directories']
    if not isinstance(names,list) or not isinstance(outputs,list) or len(set(names))!=len(names):
        raise Conflict('invalid source/output manifests')
    for name in names+outputs:relative_name(name)
    for name in names:
        if within(name,outputs):raise Conflict('source overlaps output')
    for out in outputs:
        if within(out,protected_paths) or any(within(p,[out]) for p in protected_paths):
            raise Conflict('output overlaps protected paths')
        if within(out,module_roots) or any(within(p,[out]) for p in module_roots):
            raise Conflict('output must be separate from source modules')
    if not isinstance(contract['data_references'],list) or not isinstance(contract['environment'],dict):
        raise Conflict('invalid data/environment manifest')
    for ref in contract['data_references']:
        if not isinstance(ref,dict) or set(ref)!={'path','version','sha256'} or not ref['version']:
            raise Conflict('data requires pinned version and digest')
        relative_name(ref['path'])
        if len(ref['sha256'])!=64 or any(c not in '0123456789abcdef' for c in ref['sha256']):
            raise Conflict('invalid data digest')
        if within(ref['path'],outputs) or ref['path'] in names:raise Conflict('data overlaps source/output')
    return contract


class SourceIndex:
    """Stat change index for ordinary checks; trust boundaries always hash bytes.

    This class only visits approved source names. It never discovers sources by
    entering output or data directories; adding names is an authorization action.
    """
    def __init__(self): self.entries={}

    def scan(self, root, names, *, boundary=False):
        root=Path(root).absolute();result={}
        for name in sorted(names):
            relative_name(name)
            path=root/name
            try: current=stamp(path.lstat())
            except OSError as exc: raise Conflict('source missing: '+name) from exc
            old=self.entries.get((str(root),name))
            if boundary or old is None or old[0]!=current:
                digest=stream_digest(path,root=root)
                self.entries[(str(root),name)]=(current,digest)
            else: digest=old[1]
            result[name]=digest
        for name in names:
            path=root/name
            try:current=stamp(path.lstat())
            except OSError as exc:raise Conflict('source changed during scan') from exc
            if self.entries[(str(root),name)][0]!=current:raise Conflict('source changed during scan')
        return {'files':result,'tree_sha256':sha(result)}


def source_names(repo, contract):
    """Discover additions only inside approved source modules, never data/outputs."""
    manifest=contract['manifest'];roots=contract['module_roots'];protected=contract['protected_paths']
    validate_inputs(manifest,roots,protected)
    names={name for name in manifest['source_files'] if (Path(repo)/name).exists() or not within(name,roots) or within(name,protected)}
    excluded=manifest['output_directories']+[r['path'] for r in manifest['data_references']]+['.git','.venv','__pycache__','.pytest_cache']
    repo=Path(repo)
    for module in roots:
        path=repo/module
        if path.is_file():names.add(module);continue
        for directory,dirs,files in os.walk(path,followlinks=False):
            rel=Path(directory).relative_to(repo).as_posix()
            if (Path(directory)).is_symlink():raise Conflict('source directory symlink')
            for child in dirs+files:
                target=Path(directory)/child;name=target.relative_to(repo).as_posix()
                if target.is_symlink():raise Conflict('source link requires clarification: '+name)
            dirs[:]=[d for d in dirs if not within((Path(directory)/d).relative_to(repo).as_posix(),excluded) and d not in {'__pycache__','.pytest_cache','.venv','.git'}]
            for name in files:
                relative=(Path(directory)/name).relative_to(repo).as_posix()
                if not within(relative,excluded):names.add(relative)
    for protected_path in protected:
        if protected_path=='.git':continue
        path=repo/protected_path
        if path.is_file():names.add(protected_path)
        elif path.is_dir():
            for entry in path.rglob('*'):
                if entry.is_symlink():raise Conflict('protected symlink')
                if entry.is_file():names.add(entry.relative_to(repo).as_posix())
    return sorted(names)


_DATA_VERIFIED={}


def verify_data(repo,manifest):
    # Explicit trust-boundary verification. A supplied digest alone is not proof
    # of the local bytes; no claimed upstream provenance bypasses this check.
    for ref in manifest['data_references']:
        path=Path(repo)/ref['path'];key=(str(path),ref['version'],ref['sha256'])
        current=stamp(path.lstat())
        if _DATA_VERIFIED.get(key)==current:continue
        if stream_digest(path,root=repo)!=ref['sha256']:
            raise Conflict('data reference digest mismatch: '+ref['path'])
        _DATA_VERIFIED[key]=current


def verify_environment(manifest):
    if not isinstance(manifest,dict) or not manifest:raise Conflict('nonempty pinned execution environment required')
    for name,item in manifest.items():
        if not isinstance(name,str) or not isinstance(item,dict) or set(item)!={'path','version','sha256'} or not isinstance(item['version'],str) or not item['version']:
            raise Conflict('environment entry requires path/version/sha256')
        path=Path(item['path'])
        if not path.is_absolute() or path.resolve(strict=True)!=path:raise Conflict('environment path must be absolute and canonical')
        key=(str(path),item['version'],item['sha256']);current=stamp(path.lstat())
        if _DATA_VERIFIED.get(key)==current:continue
        if stream_digest(path)!=item['sha256']:raise Conflict('execution environment changed: '+name)
        _DATA_VERIFIED[key]=current
