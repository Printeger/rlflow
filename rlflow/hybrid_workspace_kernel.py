"""Linux cooperating directory locks, NOT write permission or a runtime lease.

Fixed protected-startup paths only. No caller FD/path adoption. Direct local
ext4/xfs/btrfs/tmpfs mounts only; network/overlay provenance is not inferred.
Same-UID noncooperating writers and the trusted OS owner remain outside this
advisory boundary. No runtime or third-party native fork is supported here.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import threading

from .jobs import identity
from .store import Conflict

_live={}
_orphaned_fds={}
_registry_lock=threading.RLock()
LOCAL_FILESYSTEMS=frozenset(('ext4','xfs','btrfs','tmpfs'))


def _read_proc(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC)
    try:
        chunks=[];remaining=limit+1
        while remaining:
            part=os.read(fd,min(65536,remaining))
            if not part:break
            chunks.append(part);remaining-=len(part)
        raw=b''.join(chunks)
        if len(raw)>limit:raise Conflict('workspace Kernel metadata exceeds bound')
        return raw.decode('utf-8',errors='surrogateescape')
    finally:os.close(fd)


def _fd_scope(fd):
    info=os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):raise Conflict('workspace descriptor is not a directory')
    rows=[line.split(':',1)[1].strip() for line in _read_proc('/proc/self/fdinfo/'+str(fd),8192).splitlines()
          if line.startswith('mnt_id:')]
    if len(rows)!=1 or not rows[0].isdigit():raise Conflict('workspace mount identity unavailable')
    return (info.st_dev,info.st_ino,int(rows[0]))


def _exclusive_lock(fd,owner_pid):
    """Observe the held FLOCK; never reacquire and conceal a lost lock."""
    info=os.fstat(fd)
    rows=[line.split() for line in _read_proc('/proc/self/fdinfo/'+str(fd),8192).splitlines()
          if line.startswith('lock:')]
    if len(rows)!=1 or len(rows[0])!=9:
        raise Conflict('original workspace Kernel flock unavailable')
    row=rows[0]
    try:
        device=row[6].split(':')
        matches=(row[2:5]==['FLOCK','ADVISORY','WRITE'] and int(row[5])==owner_pid and
            len(device)==3 and int(device[0],16)==os.major(info.st_dev) and
            int(device[1],16)==os.minor(info.st_dev) and int(device[2])==info.st_ino and row[7:]==['0','EOF'])
    except ValueError:matches=False
    if not matches:raise Conflict('original workspace Kernel flock differs')


def _local_mount(mount_id):
    found=[]
    for line in _read_proc('/proc/self/mountinfo',4*1024**2).splitlines():
        prefix,separator,suffix=line.partition(' - ')
        fields=prefix.split()
        if fields and fields[0]==str(mount_id):
            tail=suffix.split()
            if not separator or len(fields)<6 or len(tail)<3:raise Conflict('workspace mount metadata invalid')
            # A subtree bind/subvolume root can conceal physical ancestors.
            # No inferred disjointness across such mount-root aliases.
            if fields[3]!='/':raise Conflict('workspace requires a direct local whole-filesystem mount root')
            found.append(tail[0])
    if len(found)!=1 or found[0] not in LOCAL_FILESYSTEMS:
        raise Conflict('workspace requires a supported direct local filesystem')
    return found[0]


@contextmanager
def _chain(path):
    path=Path(path).absolute()
    try:encoded=str(path).encode('utf-8')
    except UnicodeError:raise Conflict('workspace path invalid') from None
    if b'\x00' in encoded or '..' in path.parts or len(path.parts)>64 or len(path.parts)<3 or len(encoded)>4096:
        raise Conflict('bounded concrete workspace path required')
    fds=[];_registry_lock.acquire()
    try:
        if len(_orphaned_fds)>1024-65:raise Conflict('workspace failed cleanup capacity reached')
        fds.append(os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC))
        for part in path.parts[1:]:
            fds.append(os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1]))
        yield fds,tuple(_fd_scope(fd) for fd in fds)
    except OSError:raise Conflict('workspace path or descriptor unavailable') from None
    finally:
        errors=[]
        try:
            for fd in reversed(fds):
                try:info=os.fstat(fd)
                except OSError:errors.append(fd);continue
                try:os.close(fd)
                except OSError:
                    _orphaned_fds[fd]=(os.getpid(),info.st_dev,info.st_ino);errors.append(fd)
        finally:_registry_lock.release()
        if errors:raise Conflict('workspace ancestor cleanup failed; retained for explicit cleanup')


def cleanup_quarantine():
    """Protected same-process cleanup, never adopt a descriptor as authority."""
    with _registry_lock:
        errors=[]
        for fd,expected in tuple(_orphaned_fds.items()):
            try:
                info=os.fstat(fd)
                if (os.getpid(),info.st_dev,info.st_ino)!=expected:
                    raise Conflict('workspace quarantined descriptor identity changed')
                os.close(fd);del _orphaned_fds[fd]
            except (OSError,Conflict):errors.append(fd)
        if errors:raise Conflict('workspace quarantined cleanup remains uncertain')


def _private(fd):
    info=os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
        raise Conflict('workspace requires a private owned directory')


def _child_invalidate():
    global _registry_lock
    # Never LOCK_UN: fork shares the parent's open file description. Closing
    # only child descriptors preserves the parent's actual lock.
    for hold in tuple(_live.values()):
        for fd in (hold._fd,hold._parent_fd):
            if fd is None:continue
            try:os.close(fd)
            except OSError:pass
        hold._closed=True
    for fd in tuple(_orphaned_fds):
        try:os.close(fd)
        except OSError:pass
    _live.clear();_orphaned_fds.clear();_registry_lock=threading.RLock()


def _fork_prepare():_registry_lock.acquire()
def _fork_parent():_registry_lock.release()


os.register_at_fork(before=_fork_prepare,after_in_parent=_fork_parent,
                    after_in_child=_child_invalidate)


class DirectoryHold:
    """Long-held directory inode lock, with fixed ancestors and Kernel owner.

    Strong process-local registry intentionally retains a lost handle until
    explicit close or process death; losing a return is not automatic release.
    No deadline, source authority, persistent restore or writer operations yet.
    """
    def __init__(self,path):
        self._path=Path(path).absolute();self._fd=self._parent_fd=None;self._closed=True
        self._lock=threading.RLock();self._owner=identity(os.getpid())
        if self._owner is None:raise Conflict('actual workspace Kernel owner unavailable')
        self._mount_namespace=os.stat('/proc/thread-self/ns/mnt').st_ino
        with _registry_lock:
            if len(_live)>=128:raise Conflict('workspace Kernel hold capacity reached')
            with _chain(self._path) as (fds,chain):
                _private(fds[-1]);_private(fds[-2]);filesystem=_local_mount(chain[-1][2])
                fd=parent=None
                try:
                    fd=os.dup(fds[-1]);parent=os.dup(fds[-2])
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    self._fd,self._parent_fd=fd,parent;self._chain=chain;self.filesystem=filesystem
                    self._closed=False;self.check();_live[id(self)]=self
                except BaseException:
                    # Keep a failed cleanup reachable, and attempt BOTH FDs.
                    self._fd,self._parent_fd=fd,parent;self._chain=chain;self._closed=False
                    _live[id(self)]=self
                    try:self.close()
                    except (OSError,Conflict):pass
                    raise

    def _owner_check(self):
        if identity(os.getpid())!=self._owner:
            raise PermissionError('actual original workspace Kernel process required')

    def check(self):
        self._owner_check()
        with self._lock:
            if self._closed:raise Conflict('workspace Kernel hold closed')
            try:
                if self._fd is None or self._parent_fd is None:raise Conflict('workspace Kernel hold partially closed')
                if os.stat('/proc/thread-self/ns/mnt').st_ino!=self._mount_namespace:
                    raise Conflict('workspace mount namespace changed')
                if (_fd_scope(self._fd)!=self._chain[-1] or _fd_scope(self._parent_fd)!=self._chain[-2] or
                        os.get_inheritable(self._fd) or os.get_inheritable(self._parent_fd)):
                    raise Conflict('workspace held descriptor identity changed')
                _private(self._fd);_private(self._parent_fd)
                _exclusive_lock(self._fd,self._owner['pid'])
                with _chain(self._path) as (_,chain):
                    if chain!=self._chain:raise Conflict('workspace ancestor or directory rebound')
                return {'directory_identity':list(self._chain[-1]),'parent_identity':list(self._chain[-2]),
                    'owner':dict(self._owner),'filesystem':self.filesystem,'execution_enabled':False}
            except OSError:raise Conflict('workspace held descriptor unavailable') from None

    def close(self):
        self._owner_check()
        with self._lock,_registry_lock:
            if self._closed:return
            # No path reopen, unlink or LOCK_UN. Do not close an unrelated FD
            # if trusted process code has externally closed/reused our number.
            errors=[]
            for name,expected in (('_fd',self._chain[-1]),('_parent_fd',self._chain[-2])):
                fd=getattr(self,name)
                if fd is None:continue
                try:
                    if _fd_scope(fd)!=expected:raise Conflict('workspace descriptor replaced before close')
                    os.close(fd)
                    setattr(self,name,None)
                except (OSError,Conflict) as error:errors.append(error)
            if errors:raise Conflict('workspace close identity or cleanup failed')
            self._closed=True;_live.pop(id(self),None)
