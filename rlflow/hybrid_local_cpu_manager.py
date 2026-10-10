"""Finite original user-manager connection; no Core authority or cold adoption.

Source owns this object before connect. Its exact unit comes from the original
source capability, not a caller name. StopUnit return is intent, JobRemoved(done)
is completion. Connection/job outcome loss remains UNKNOWN and never resends.
"""
import ctypes as C
from dataclasses import dataclass
import errno
import hashlib
import json
import os
import re
import stat
import time
import uuid

from .jobs import identity
from .store import Conflict

DEST=b'org.freedesktop.systemd1'
PATH=b'/org/freedesktop/systemd1'
MANAGER=b'org.freedesktop.systemd1.Manager'
UNIT=b'org.freedesktop.systemd1.Unit'
SERVICE=b'org.freedesktop.systemd1.Service'
_originals={}
_stop_replies={}
P=C.c_void_p
CALLBACK=C.CFUNCTYPE(C.c_int,P,P,P)


@dataclass(frozen=True,eq=False)
class _OriginalStopReply:
    owner: object
    context: bytes
    job: str


def _library():
    lib=C.CDLL('/usr/lib/x86_64-linux-gnu/libsystemd.so.0')
    signatures={
        'sd_bus_new':([C.POINTER(P)],C.c_int),
        'sd_bus_set_address':([P,C.c_char_p],C.c_int),
        'sd_bus_set_bus_client':([P,C.c_int],C.c_int),
        'sd_bus_start':([P],C.c_int),
        'sd_bus_get_fd':([P],C.c_int),
        'sd_bus_set_method_call_timeout':([P,C.c_uint64],C.c_int),
        'sd_bus_call_method':([P,C.c_char_p,C.c_char_p,C.c_char_p,C.c_char_p,P,C.POINTER(P),C.c_char_p],C.c_int),
        'sd_bus_message_read':([P,C.c_char_p],C.c_int),
        'sd_bus_get_property':([P,C.c_char_p,C.c_char_p,C.c_char_p,C.c_char_p,P,C.POINTER(P),C.c_char_p],C.c_int),
        'sd_bus_message_read_array':([P,C.c_char,C.POINTER(P),C.POINTER(C.c_size_t)],C.c_int),
        'sd_bus_message_enter_container':([P,C.c_char,C.c_char_p],C.c_int),
        'sd_bus_message_exit_container':([P],C.c_int),
        'sd_bus_add_match':([P,C.POINTER(P),C.c_char_p,CALLBACK,P],C.c_int),
        'sd_bus_process':([P,P],C.c_int),
        'sd_bus_wait':([P,C.c_uint64],C.c_int),
        'sd_bus_message_unref':([P],P),
        'sd_bus_slot_unref':([P],P),
        'sd_bus_close_unref':([P],P),
    }
    for name,(args,result) in signatures.items():
        function=getattr(lib,name);function.argtypes=args;function.restype=result
    return lib


def _ok(value):
    if value<0:raise OSError(-value,os.strerror(-value))
    return value


class OriginalServiceManager:
    def __init__(self,source,row):
        from .hybrid_local_cpu_source import LocalCpuSourceOwner
        import json
        if type(source) is not LocalCpuSourceOwner or source._issued(row['source']) is not row:
            raise PermissionError('original configurable CPU source required for manager')
        source._runtime_spec(row)
        unit=json.loads(row['source'].raw)['local_cpu_binding']['unit']
        if not re.fullmatch(r'rlflow-local-[0-9a-f]{32}\.service',unit):
            raise Conflict('original finite service name required')
        self.source=source;self.row=row;self.unit=unit;self.creator=identity(os.getpid())
        self.lib=_library();self.bus=P();self.slot=P();self.fd=None;self.fd_identity=None
        self.destination=None;self.unit_path=None;self.bound=None
        self.unit_referenced=False
        self.stop_entered=False;self.stop_job=None;self.stop_receipt=None
        self._stop_wire_entered=False
        self._stop_nonce=uuid.uuid4().hex
        self.stopped_raw=None
        self.events=[];self.callback_error=None;self.closed=False
        self.observed_snapshots=[]
        self.callback=CALLBACK(self._job_removed)
        if len(_originals)>=128:raise Conflict('finite original manager capacity exceeded')
        _originals[id(self)]=self  # Before any manager connection effect.

    def _actual(self):
        if (type(self) is not OriginalServiceManager or _originals.get(id(self)) is not self or
                identity(os.getpid())!=self.creator):
            raise PermissionError('exact original manager owner required')
        self.source._actual()
        if self.source._issued(self.row['source']) is not self.row:
            raise PermissionError('same original manager source required')

    def connect(self):
        self._actual()
        if self.bus.value or self.closed:raise Conflict('original manager connection cannot be replaced')
        _ok(self.lib.sd_bus_new(C.byref(self.bus)))
        _ok(self.lib.sd_bus_set_address(self.bus,f'unix:path=/run/user/{os.geteuid()}/bus'.encode()))
        _ok(self.lib.sd_bus_set_bus_client(self.bus,1))
        _ok(self.lib.sd_bus_set_method_call_timeout(self.bus,2_000_000))
        _ok(self.lib.sd_bus_start(self.bus))
        self.fd=_ok(self.lib.sd_bus_get_fd(self.bus));info=os.fstat(self.fd)
        self.fd_identity=(info.st_dev,info.st_ino)
        if not stat.S_ISSOCK(info.st_mode) or os.get_inheritable(self.fd):
            raise Conflict('original private manager socket required')
        self.destination=self._call('GetNameOwner',b's',DEST,return_type=b's',
                    destination=b'org.freedesktop.DBus',path=b'/org/freedesktop/DBus',interface=b'org.freedesktop.DBus')
        rule=("type='signal',sender='"+self.destination+"',path='/org/freedesktop/systemd1',"
              "interface='org.freedesktop.systemd1.Manager',member='JobRemoved'").encode()
        _ok(self.lib.sd_bus_add_match(self.bus,C.byref(self.slot),rule,self.callback,None))
        self._call('Subscribe',b'')

    def _check_socket(self):
        self._actual()
        if self.closed or self.fd is None or not self.bus.value:raise Conflict('original manager connection unavailable')
        info=os.fstat(self.fd)
        if (info.st_dev,info.st_ino)!=self.fd_identity or os.get_inheritable(self.fd):
            raise Conflict('original manager socket identity differs')

    def _call(self,name,types,*args,return_type=None,destination=None,path=PATH,interface=MANAGER):
        reply=P()
        try:
            if name=='StopUnit':
                self._check_socket()
                if (not self.stop_entered or self._stop_wire_entered or self.bound is None or id(self) in _stop_replies or
                        types!=b'ss' or args!=(self.unit.encode(),b'fail') or return_type!=b'o' or
                        destination is not None or path!=PATH or interface!=MANAGER):
                    raise Conflict('same original entered STOP call required; no reissue')
                self._stop_wire_entered=True
            _ok(self.lib.sd_bus_call_method(self.bus,destination or self.destination.encode(),path,interface,
                name.encode(),None,C.byref(reply),types,*args))
            if return_type is None:return None
            if return_type==b'a(sus)':
                _ok(self.lib.sd_bus_message_enter_container(reply,b'a',b'(sus)'));pids=[]
                while _ok(self.lib.sd_bus_message_enter_container(reply,b'r',b'sus')):
                    group=C.c_char_p();pid=C.c_uint32();command=C.c_char_p()
                    _ok(self.lib.sd_bus_message_read(reply,b'sus',C.byref(group),C.byref(pid),C.byref(command)))
                    pids.append(pid.value)
                    if len(pids)>128:raise Conflict('original finite manager process bound exceeded')
                    _ok(self.lib.sd_bus_message_exit_container(reply))
                _ok(self.lib.sd_bus_message_exit_container(reply))
                return pids
            value=C.c_char_p();_ok(self.lib.sd_bus_message_read(reply,return_type,C.byref(value)))
            if value.value is None:raise Conflict('original manager reply missing')
            value=value.value.decode()
            if name=='StopUnit':
                # Actual authenticated wire reply, retained BEFORE caller
                # return or unref can fail. Not JobRemoved completion.
                if re.fullmatch(r'/org/freedesktop/systemd1/job/[1-9][0-9]{0,9}',value) is None:
                    raise Conflict('original STOP job path invalid')
                from .store import canonical
                _stop_replies[id(self)]=_OriginalStopReply(self,canonical(self._stop_reply_context(value)),value)
            return value
        finally:
            if reply.value:self.lib.sd_bus_message_unref(reply)

    def _stop_reply_context(self,job):
        self._check_socket()
        if self.row.get('manager') is not self or self.bound is None or not self.stop_entered or not self._stop_wire_entered:
            raise Conflict('original STOP reply owner binding differs')
        return {'job':job,'creator':self.creator,'destination':self.destination,'unit':self.unit,
                'keeper':self.bound,'socket_identity':list(self.fd_identity),
                'source_sha256':hashlib.sha256(self.row['source'].raw).hexdigest(),'stop_intent':self._stop_nonce}

    def _original_stop_job(self):
        self._check_socket()
        receipt=_stop_replies.get(id(self))
        if receipt is None:raise Conflict('original StopUnit wire reply UNKNOWN; no reissue')
        from .store import canonical
        if (type(receipt) is not _OriginalStopReply or receipt.owner is not self or
                receipt.context!=canonical(self._stop_reply_context(receipt.job))):
            raise Conflict('original StopUnit wire reply context differs')
        return receipt.job

    def _property(self,name,kind,interface=UNIT):
        reply=P()
        try:
            _ok(self.lib.sd_bus_get_property(self.bus,self.destination.encode(),self.unit_path.encode(),
                    interface,name.encode(),None,C.byref(reply),kind))
            if kind==b'ay':
                value=P();size=C.c_size_t()
                _ok(self.lib.sd_bus_message_read_array(reply,b'y',C.byref(value),C.byref(size)))
                if size.value!=16:raise Conflict('original InvocationID unavailable')
                return C.string_at(value,size.value).hex()
            value=(C.c_char_p() if kind==b's' else C.c_uint32() if kind==b'u' else
                   C.c_uint64() if kind==b't' else C.c_int32())
            _ok(self.lib.sd_bus_message_read(reply,kind,C.byref(value)))
            return value.value.decode() if kind==b's' else value.value
        finally:
            if reply.value:self.lib.sd_bus_message_unref(reply)

    def snapshot(self):
        self._check_socket()
        if self.unit_path is None:self.unit_path=self._call('GetUnit',b's',self.unit.encode(),return_type=b'o')
        # The original RefUnit still preserves proofs through STOP/FD closure.
        # After owner death its bus reference vanishes; failed transient units
        # must not accumulate forever. This does not release business exposure.
        if self._property('CollectMode',b's')!='inactive-or-failed':
            raise Conflict('original finite manager collection policy differs')
        result={name:self._property(name,kind,interface) for name,kind,interface in
            (('InvocationID',b'ay',UNIT),('ActiveState',b's',UNIT),('SubState',b's',UNIT),
             ('MainPID',b'u',SERVICE),('ExecMainPID',b'u',SERVICE),('ExecMainCode',b'i',SERVICE),
             ('ExecMainStatus',b'i',SERVICE),('Result',b's',SERVICE),('KillMode',b's',SERVICE),
             ('SendSIGKILL',b'b',SERVICE),('TimeoutStopUSec',b't',SERVICE))}
        if len(self.observed_snapshots)<16:self.observed_snapshots.append(dict(result))
        if result['KillMode']!='control-group' or result['SendSIGKILL']!=1 or result['TimeoutStopUSec']!=2_000_000:
            raise Conflict('original full-scope bounded manager STOP policy differs: '+repr(result))
        if self.bound is not None and result['InvocationID']!=self.bound['invocation_id']:
            raise Conflict('original manager Invocation replaced; no adoption')
        return result

    def bind_ready(self,keeper):
        self._check_socket()
        if self.bound is not None:raise Conflict('original keeper cannot be rebound')
        # GetUnit's name/path is NOT a reference. Keep the original transient
        # object alive through job completion; auto-unref on original bus close.
        self._call('RefUnit',b's',self.unit.encode());self.unit_referenced=True
        value=self.snapshot()
        if (value['InvocationID']!=keeper['invocation_id'] or value['MainPID']!=keeper['pid'] or
                value['ExecMainPID']!=keeper['pid']):
            raise Conflict('original keeper/manager ready identity differs')
        self.bound=dict(keeper)

    def _job_removed(self,message,userdata,error):
        try:
            number=C.c_uint32();path=C.c_char_p();unit=C.c_char_p();result=C.c_char_p()
            _ok(self.lib.sd_bus_message_read(message,b'uoss',C.byref(number),C.byref(path),C.byref(unit),C.byref(result)))
            if unit.value==self.unit.encode():
                if len(self.events)>=8:raise Conflict('finite original manager job receipt bound exceeded')
                self.events.append(dict(id=number.value,path=path.value.decode(),unit=unit.value.decode(),result=result.value.decode()))
            return 1
        except BaseException as exc:self.callback_error=exc;return -errno.EIO

    def stop(self):
        self._actual()
        if self.stopped_raw is not None:return json.loads(self.stopped_raw)
        self._check_socket()
        if self.bound is None:raise Conflict('original manager keeper binding unavailable')
        self.snapshot()  # Current same Invocation BEFORE any STOP effect.
        if not self.stop_entered:
            self.stop_entered=True  # Lost method return never reissues StopUnit.
            try:
                returned=self._call('StopUnit',b'ss',self.unit.encode(),b'fail',return_type=b'o')
            except Exception:
                # Fully decoded original receipt only. Missing wire reply
                # stays UNKNOWN; no resend and no fatal BaseException swallowing.
                self.stop_job=self._original_stop_job()
            else:
                original=self._original_stop_job()
                if returned!=original:raise Conflict('original STOP return differs from wire reply')
                self.stop_job=original
        original=self._original_stop_job()
        if self.stop_job is None:self.stop_job=original
        elif self.stop_job!=original:raise Conflict('original STOP job differs from wire reply')
        end=time.monotonic()+3
        while self.stop_receipt is None:
            if self.callback_error is not None:raise Conflict('original manager job stream UNKNOWN') from self.callback_error
            for event in self.events:
                if event['path']==self.stop_job:
                    if event['result']!='done':raise Conflict('original manager STOP job not done')
                    self.stop_receipt=dict(event);break
            if self.stop_receipt is not None:break
            if time.monotonic()>=end:raise Conflict('original manager STOP job receipt UNKNOWN')
            if not _ok(self.lib.sd_bus_process(self.bus,None)):
                _ok(self.lib.sd_bus_wait(self.bus,50_000))
        value=self.snapshot()
        if value['MainPID']!=0 or (value['ActiveState'],value['SubState']) not in (('inactive','dead'),('failed','failed')):
            raise Conflict('original manager scope not terminal')
        pids=self._call('GetUnitProcesses',b's',self.unit.encode(),return_type=b'a(sus)')
        if pids:raise Conflict('original manager scope still has processes')
        result={'unit':self.unit,'keeper':self.bound,'job':dict(self.stop_receipt),'manager':value,
                'original_manager_scope_processes':pids,'unit_reference_held':self.unit_referenced}
        from .store import canonical
        self.stopped_raw=canonical(result)
        return json.loads(self.stopped_raw)

    def close(self):
        self._actual()
        if self.closed:return
        if self.fd is not None:
            info=os.fstat(self.fd)
            if self.fd_identity is None or (info.st_dev,info.st_ino)!=self.fd_identity:
                raise Conflict('original manager FD closure identity UNKNOWN')
        if self.slot.value:self.lib.sd_bus_slot_unref(self.slot);self.slot=P()
        if self.bus.value:self.lib.sd_bus_close_unref(self.bus);self.bus=P()
        if self.fd is not None:
            try:os.fstat(self.fd)
            except OSError as exc:
                if exc.errno!=errno.EBADF:raise
            else:raise Conflict('original manager FD closure not proved')
        self.fd=None;self.closed=True
