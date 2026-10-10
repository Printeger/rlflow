"""Held Linux executable/stdio observations; NOT account/model/usage authority.

Only the original Source binds these observations to its original process.
This helper cannot start a process, send G, read credentials or issue a grant.
"""
import os
import json

from .store import Conflict,canonical


class _ExecFDObservation:
    def __init__(self):
        self.rows=[];self.entered=False;self._raw=None

    @property
    def value(self):
        return None if self._raw is None else json.loads(self._raw)

    def _pin(self,path):
        fd=os.open(path,os.O_PATH|os.O_CLOEXEC)
        row={'fd':fd,'identity':None};self.rows.append(row)
        info=os.fstat(fd);row['identity']=(info.st_dev,info.st_ino)
        return row['identity']

    def observe(self,pid,*,binary_identity,stdout_identity,stderr_identity,check_live):
        if self.entered:raise Conflict('original executable observation already entered; no replacement')
        self.entered=True
        check_live()
        root='/proc/'+str(pid)
        binary=self._pin(root+'/exe')
        if binary!=tuple(binary_identity):
            raise Conflict('original producer has not execed the approved ELF')
        stdout=self._pin(root+'/fd/1');stderr=self._pin(root+'/fd/2')
        if stdout!=tuple(stdout_identity) or stderr!=tuple(stderr_identity):
            raise Conflict('original executable stdio differs from held Source')
        check_live()  # Same pidfd/starttime after all proc opens, not PID reuse.
        self._raw=canonical({'pid':pid,'binary_identity':list(binary),
            'stdout_identity':list(stdout),'stderr_identity':list(stderr)})
        return self.value

    def descriptors(self):
        return tuple(row['fd'] for row in self.rows if row['fd'] is not None)

    def close(self):
        errors=[]
        for row in self.rows:
            if row['fd'] is None:continue
            try:
                info=os.fstat(row['fd'])
                if row['identity'] is None or (info.st_dev,info.st_ino)!=row['identity']:
                    raise Conflict('original executable observation descriptor identity unavailable')
                os.close(row['fd']);row['fd']=None
            except (OSError,Conflict) as error:errors.append(error)
        if errors:raise Conflict('original executable observation cleanup incomplete') from errors[0]
