"""Private bounded file-cache transfer, NOT authentication qualification.

No JWT parsing, credential logging, keyring access, login, account switching,
model call or mutation of the host cache. Only the original runtime invokes
this after its current approval/Controller checks. Tests use synthetic files.
"""
import os
from pathlib import Path
import stat

from .store import Conflict


class _AccountCache:
    LIMIT=65536

    def __init__(self,home,destination,*,destination_identity):
        self.home=home;self.destination=destination
        self.destination_identity=tuple(destination_identity)
        self.rows=[];self.entered=False;self.staged=False;self.pending=False
        self.destination_fd=None
        self.target_fd=None;self.target_identity=None

    def _keep(self,fd):
        row={'fd':fd,'identity':None};self.rows.append(row)
        info=os.fstat(fd);row['identity']=(info.st_dev,info.st_ino)
        return fd

    def _directory(self,path):
        # Walk every component through held NOFOLLOW dirfds; never resolve
        # a caller symlink and then read a different account's cache.
        path=Path(path)
        if not path.is_absolute() or '..' in path.parts:
            raise Conflict('absolute original account-cache home required')
        fd=self._keep(os.open('/',os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC))
        for name in path.parts[1:]:
            fd=self._keep(os.open(name,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd))
        info=os.fstat(fd)
        if info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise Conflict('private current account-cache directory required')
        return fd

    def stage(self,effect_check):
        if self.entered:raise Conflict('account-cache transfer already entered; no replacement')
        self.entered=True
        source_dir=self._directory(self.home)
        source=self._keep(os.open('auth.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=source_dir))
        info=os.fstat(source)
        stamp=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or
                stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or
                not 0<info.st_size<=self.LIMIT):
            raise Conflict('bounded private original account-cache file required')
        # Final current-state gate before the first secret read. Never return
        # or persist raw bytes, token claims or a credential digest as evidence.
        effect_check()
        raw=os.pread(source,self.LIMIT+1,0)
        if len(raw)!=info.st_size or stamp(os.fstat(source))!=stamp(info):
            raise Conflict('original account cache changed during transfer')
        destination=self._directory(self.destination);self.destination_fd=destination
        info=os.fstat(destination)
        if (info.st_dev,info.st_ino)!=self.destination_identity:
            raise Conflict('original frozen session cache directory differs')
        effect_check()
        target=os.open('auth.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
            0o600,dir_fd=destination)
        self.pending=True
        self.target_fd=target
        self._keep(target)
        info=os.fstat(target);self.target_identity=(info.st_dev,info.st_ino)
        remaining=memoryview(raw)
        while remaining:
            count=os.write(target,remaining)
            if count<=0:raise Conflict('private account-cache copy incomplete')
            remaining=remaining[count:]
        os.fsync(target)
        self.staged=True
        return {'cache_staged':True,'account_qualified':False,'model_released':False}

    def descriptors(self):
        return tuple(row['fd'] for row in self.rows if row['fd'] is not None)

    def close(self):
        # Delete only the named session copy through its originally held
        # private directory. The host auth.json is NEVER modified or removed.
        errors=[]
        if self.pending:
            try:
                directory=os.fstat(self.destination_fd)
                row=next(row for row in self.rows if row['fd']==self.destination_fd)
                if row['identity'] is None or (directory.st_dev,directory.st_ino)!=row['identity']:
                    raise Conflict('original session cache directory descriptor changed')
                info=os.stat('auth.json',dir_fd=self.destination_fd,follow_symlinks=False)
                if (self.target_identity is None or (info.st_dev,info.st_ino)!=self.target_identity or
                        not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1):
                    raise Conflict('session cache cleanup identity unavailable')
                os.unlink('auth.json',dir_fd=self.destination_fd);self.pending=False
            except FileNotFoundError:
                # Absence of this name does not prove the original secret was
                # deleted: a renamed/hardlinked inode must remain UNKNOWN.
                try:
                    info=os.fstat(self.target_fd)
                    if self.target_identity is not None and (info.st_dev,info.st_ino)==self.target_identity and info.st_nlink==0:
                        self.pending=False
                    else:errors.append(Conflict('original session cache may be renamed; cleanup UNKNOWN'))
                except (OSError,Conflict) as error:errors.append(error)
            except (OSError,Conflict) as error:errors.append(error)
        # Keep the directory alive until deletion is proven, for a safe retry.
        for row in self.rows:
            if row['fd'] is None or self.pending and row['fd'] in (self.destination_fd,self.target_fd):continue
            try:
                info=os.fstat(row['fd'])
                if row['identity'] is None or (info.st_dev,info.st_ino)!=row['identity']:
                    raise Conflict('original account-cache descriptor identity unavailable')
                os.close(row['fd']);row['fd']=None
            except (OSError,Conflict) as error:errors.append(error)
        if errors:raise Conflict('original account-cache cleanup incomplete') from errors[0]
