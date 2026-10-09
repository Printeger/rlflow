"""Kernel-backed task limits. Observations never substitute for enforcement."""
import ctypes
import fcntl
import os
from pathlib import Path
import re
import struct
from .store import Conflict
from .jobs import owns

CGROUP=Path('/sys/fs/cgroup')


def membership(pid):
    rows=Path(f'/proc/{pid}/cgroup').read_text().splitlines()
    value=next((r[3:] for r in rows if r.startswith('0::')),None)
    if value is None:raise Conflict('cgroup v2 membership unavailable')
    return CGROUP/value.lstrip('/')


def validate_policy(policy):
    fields={'mode','memory_max','cpu_max','pids_max','disk_bytes','disk_inodes','cpu_seconds'}
    if not isinstance(policy,dict) or set(policy)!=fields:raise Conflict('complete resource policy required')
    if policy['mode'] not in {'strict','compatible_cpu'}:raise Conflict('unknown resource enforcement mode')
    for field in fields-{'mode','cpu_max'}:
        if type(policy[field]) is not int or policy[field]<=0:raise Conflict('invalid resource limit: '+field)
    if not isinstance(policy['cpu_max'],str) or not re.fullmatch(r'[1-9][0-9]* [1-9][0-9]*',policy['cpu_max']):
        raise Conflict('cpu.max requires finite quota and period')
    quota,period=map(int,policy['cpu_max'].split())
    if quota<1000 or not 1000<=period<=1000000:raise Conflict('invalid CPU bandwidth')
    return policy


def stats(group):
    group=Path(group)
    result={}
    for name in ('memory.current','memory.peak','pids.current','pids.peak','cpu.stat','memory.events','pids.events','cgroup.events'):
        raw=(group/name).read_text().strip()
        result[name]=int(raw) if raw.isdigit() else {k:int(v) for k,v in (line.split() for line in raw.splitlines())}
    return result


def prepare_group(root, name, policy):
    validate_policy(policy)
    root=Path(root).resolve(strict=True)
    if not root.is_relative_to(CGROUP) or not re.fullmatch('[A-Za-z0-9_-]+',name):raise Conflict('invalid delegated task group')
    controllers=set((root/'cgroup.subtree_control').read_text().split())
    if not {'cpu','memory','pids'}<=controllers:raise Conflict('delegated controllers are not enabled')
    group=root/name;group.mkdir()  # Never silently reuse an unsettled group.
    try:
        for filename,value in [('memory.max',policy['memory_max']),('memory.swap.max',0),('cpu.max',policy['cpu_max']),('pids.max',policy['pids_max']),('memory.oom.group',1)]:
            (group/filename).write_text(str(value))
            if (group/filename).read_text().strip()!=str(value):raise Conflict('effective resource limit differs: '+filename)
    except Exception:
        group.rmdir();raise
    return {'path':str(group),'inode':group.stat().st_ino,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'policy':policy}


def verify_group(record, process=None):
    group=Path(record['path']).resolve(strict=True)
    if not group.is_relative_to(CGROUP) or group.stat().st_ino!=record['inode'] or record['boot_id']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise Conflict('resource group identity changed')
    for filename,key in [('memory.max','memory_max'),('cpu.max','cpu_max'),('pids.max','pids_max')]:
        if (group/filename).read_text().strip()!=str(record['policy'][key]):raise Conflict('resource limit drift')
    if process is not None and (not owns(process) or membership(process['pid'])!=group):
        raise Conflict('business process outside reserved task group')
    return group


def enter(record):
    group=verify_group(record)
    (group/'cgroup.procs').write_text(str(os.getpid()))
    if membership(os.getpid())!=group:raise Conflict('task cgroup entry failed')


def quota(directory, device, reader=None):
    """Read Linux project quota from the kernel, not a user assertion or disk monitor."""
    directory=Path(directory).resolve(strict=True)
    device=Path(device).resolve(strict=True)
    if directory.stat().st_dev!=device.stat().st_rdev:raise Conflict('quota device does not own directory')
    if reader is not None:
        import subprocess,json,hashlib
        helper=Path(reader['path']).resolve(strict=True)
        for entry in [helper,*helper.parents]:
            info=entry.stat()
            if info.st_uid!=0 or info.st_mode&0o022:raise Conflict('quota reader is not administrator controlled')
        if hashlib.sha256(helper.read_bytes()).hexdigest()!=reader['sha256']:raise Conflict('quota reader identity changed')
        result=subprocess.run(['/usr/bin/sudo','-n',str(helper),str(directory),str(device)],capture_output=True,text=True,timeout=5)
        if result.returncode:raise Conflict('privileged quota reader unavailable: '+result.stderr.strip())
        observed=json.loads(result.stdout)
        if observed.get('path')!=str(directory) or observed.get('device')!=str(device):raise Conflict('quota reader scope mismatch')
        return observed
    descriptor=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        data=bytearray(28);fcntl.ioctl(descriptor,0x801c581f,data,True)
    finally:os.close(descriptor)
    flags,_,_,project,_=struct.unpack('IIIII',data[:20])
    if not flags & 0x200:raise Conflict('quota directory lacks project inheritance')
    class Dqblk(ctypes.Structure):
        _fields_=[(name,ctypes.c_uint64) for name in ('bhard','bsoft','space','ihard','isoft','inodes','btime','itime')]+[('valid',ctypes.c_uint32)]
    info=Dqblk();libc=ctypes.CDLL(None,use_errno=True)
    command=(0x800007<<8)|2  # Q_GETQUOTA / PRJQUOTA, limits are 1 KiB quota blocks.
    if libc.quotactl(ctypes.c_int(command),os.fsencode(device),ctypes.c_int(project),ctypes.byref(info))!=0:
        error=ctypes.get_errno();raise Conflict('kernel project quota unavailable: '+os.strerror(error))
    if info.bhard==0 or info.ihard==0:raise Conflict('finite disk byte and inode hard quotas required')
    return {'path':str(directory),'device':str(device),'project_id':project,'hard_bytes':info.bhard*1024,
            'hard_inodes':info.ihard,'used_bytes':info.space,'used_inodes':info.inodes}


def admit(policy, group_record=None, disk=None):
    validate_policy(policy);missing=[]
    if group_record is None:missing.append('task cgroup')
    else:
        verify_group(group_record)
        if group_record['policy']!=policy:raise Conflict('group not bound to resource policy')
    if disk is None:missing.append('disk byte/inode hard quota')
    else:
        current=quota(disk['path'],disk['device'],disk.get('reader'))
        if current['hard_bytes']<=0 or current['hard_inodes']<=0:raise Conflict('finite disk hard quotas required')
        if current['hard_bytes']>policy['disk_bytes'] or current['hard_inodes']>policy['disk_inodes']:
            raise Conflict('disk quota exceeds authorized maximum')
    if policy['mode']=='strict' and missing:raise Conflict('strict resource capabilities unavailable: '+', '.join(missing))
    return {'enforced':not missing,'missing_guarantees':missing}


def reserve_task(store, stage, session_id):
    from .hybrid_runtime_boundary import check_request
    check_request(stage, store.root)
    import json
    policy=stage.get('resource_policy')
    if policy is None:return None,None,None
    config_path=store.root/'runtime/resource-config.json'
    config=json.loads(config_path.read_text()) if config_path.exists() else {}
    disk=config.get('quota_directory')
    if policy['mode']=='strict':
        if disk is None:raise Conflict('strict resource capabilities unavailable: configured project quota')
        observed=quota(disk['path'],disk['device'],disk.get('reader'))
        if not Path(stage['repo']).resolve().is_relative_to(Path(disk['path']).resolve()):
            raise Conflict('strict candidate writes must be inside configured quota directory')
        if store.root.resolve().is_relative_to(Path(disk['path']).resolve()):
            raise Conflict('control ledger must be outside artifact quota')
        if not observed['hard_bytes'] or not observed['hard_inodes']:raise Conflict('disk hard quota is unlimited')
    root=config.get('delegated_root')
    if root and membership(os.getpid())!=Path(root)/'control':
        raise Conflict('controller is outside delegated control group')
    if not root:
        return None,admit(policy,None,disk),None
    record=prepare_group(root,session_id,policy)
    try:
        guarantees=admit(policy,record,disk)
    except Exception:
        Path(record['path']).rmdir();raise
    scratch=None
    if disk:
        base=Path(disk['path'])/('role-'+session_id);base.mkdir()
        scratch=base/'scratch';scratch.mkdir()
        raw=base/'raw';raw.mkdir(mode=0o700)
        record['disk']={'root':str(Path(disk['path']).resolve()),'raw':str(raw),'directory':disk}
    return record,guarantees,scratch


def confine_writes(quota_root):
    """Inherited Landlock write confinement for the CLI and every descendant.

    Reads and network remain available to the trusted CLI. Existing CPU tools
    install their stricter read/network sandbox on top of this restriction.
    """
    import errno
    import platform
    if platform.machine()!='x86_64':raise Conflict('unverified write-confinement syscall ABI')
    libc=ctypes.CDLL(None,use_errno=True)
    def check(result,operation):
        if result<0:raise Conflict(operation+': '+os.strerror(ctypes.get_errno()))
        return result
    if check(libc.syscall(444,0,0,1),'Landlock ABI')<3:raise Conflict('Landlock truncate protection unavailable')
    handled=(1<<15)-1
    class Ruleset(ctypes.Structure):_fields_=[('handled',ctypes.c_uint64)]
    class Rule(ctypes.Structure):
        _pack_=1
        _fields_=[('rights',ctypes.c_uint64),('parent',ctypes.c_int)]
    ruleset=Ruleset(handled);fd=check(libc.syscall(444,ctypes.byref(ruleset),ctypes.sizeof(ruleset),0),'create confinement')
    try:
        for path,rights in [('/',1|4|8),(str(Path(quota_root).resolve(strict=True)),handled&~((1<<6)|(1<<9))),('/dev/null',2|4)]:
            parent=os.open(path,os.O_PATH|os.O_CLOEXEC)
            try:
                rule=Rule(rights,parent);check(libc.syscall(445,fd,1,ctypes.byref(rule),0),'add confinement')
            finally:os.close(parent)
        check(libc.prctl(38,1,0,0,0),'no_new_privs');check(libc.syscall(446,fd,0),'restrict writes')
    finally:os.close(fd)
    sec=ctypes.CDLL('libseccomp.so.2',use_errno=True)
    sec.seccomp_init.argtypes=[ctypes.c_uint32];sec.seccomp_init.restype=ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p]
    sec.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    sec.seccomp_load.argtypes=[ctypes.c_void_p];sec.seccomp_release.argtypes=[ctypes.c_void_p]
    context=sec.seccomp_init(0x7fff0000)
    if not context:raise Conflict('confinement seccomp init failed')
    try:
        for name in ('mount','umount2','pivot_root','chroot','unshare','setns','open_by_handle_at','io_uring_setup','ptrace','process_vm_writev','pidfd_getfd'):
            number=sec.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and sec.seccomp_rule_add(context,0x50000|errno.EPERM,number,0):raise Conflict('confinement seccomp rule failed')
        if sec.seccomp_load(context):raise Conflict('confinement seccomp load failed')
    finally:sec.seccomp_release(context)
