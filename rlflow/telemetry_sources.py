"""Bounded read-only Linux observations; no authority or model inference."""
import contextlib
import os
import stat
import time
from .observation import public_id, valid_id
from .startup_observation import identity_valid, number, read_json
from .store import sha
from .tool_journal import context_valid


def read_text(path,limit=65536):
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('invalid telemetry source')
        value = stream.read(limit+1)
        if len(value)>limit:raise ValueError('telemetry source exceeds bound')
        return value.decode('ascii')


def boot_id():
    return read_text('/proc/sys/kernel/random/boot_id',128).strip()


def host(root,previous=None):
    cpu = dict(scope='HOST',status='UNKNOWN',utilization_percent=None)
    memory = dict(scope='HOST',status='UNKNOWN',total_bytes=None,available_bytes=None)
    disk = dict(scope='STATE_FILESYSTEM',status='UNKNOWN',total_bytes=None,available_bytes=None)
    counters = None
    try:
        # First aggregate line only: no per-core unbounded enumeration. Guest
        # counters are already included in user/nice, so use only first 8.
        values = [int(v) for v in read_text('/proc/stat').splitlines()[0].split()[1:9]]
        if len(values)!=8 or min(values)<0:raise ValueError('invalid CPU counters')
        counters = dict(total=sum(values),idle=values[3]+values[4])
        if previous and counters['total']>previous['total'] and counters['idle']>=previous['idle']:
            total,idle = counters['total']-previous['total'],counters['idle']-previous['idle']
            if idle<=total:cpu.update(status='KNOWN',utilization_percent=100*(total-idle)/total)
    except (OSError,ValueError,IndexError,KeyError):pass
    try:
        fields = {line.split(':',1)[0]:line.split(':',1)[1].split() for line in read_text('/proc/meminfo').splitlines() if ':' in line}
        total,available = fields['MemTotal'],fields['MemAvailable']
        if total[1]!='kB' or available[1]!='kB' or not 0<=int(available[0])<=int(total[0]):raise ValueError('invalid memory counters')
        memory.update(status='KNOWN',total_bytes=int(total[0])*1024,available_bytes=int(available[0])*1024)
    except (OSError,ValueError,IndexError,KeyError):pass
    try:
        value = os.statvfs(root)
        total,available = value.f_blocks*value.f_frsize,value.f_bavail*value.f_frsize
        if not 0<=available<=total:raise ValueError('invalid filesystem counters')
        disk.update(status='KNOWN',total_bytes=total,available_bytes=available)
    except (OSError,ValueError):pass
    return dict(cpu=cpu,memory=memory,disk=disk),counters


def process(owner):
    result = dict(scope='SUPERVISOR_PROCESS',status='UNKNOWN',cpu_seconds=None,rss_bytes=None)
    if not identity_valid(owner):return result
    try:
        fd = os.open(f"/proc/{owner['pid']}",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            def read_stat():
                item = os.open('stat',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                with os.fdopen(item,'rb') as stream:
                    value = stream.read(4097)
                    if len(value)>4096:raise ValueError('process stat exceeds bound')
                    return value.decode('ascii').rsplit(')',1)[1].split()
            fields = read_stat()
            actual = dict(pid=owner['pid'],pgid=int(fields[2]),starttime=fields[19],boot_id=boot_id())
            if fields[0]=='Z' or actual!=owner:return result
            cpu = (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
            rss = int(fields[21])*os.sysconf('SC_PAGE_SIZE')
            after = read_stat()
            if after[0]=='Z' or int(after[2])!=owner['pgid'] or after[19]!=owner['starttime'] or not number(cpu) or rss<0:return result
            result.update(status='KNOWN',cpu_seconds=cpu,rss_bytes=rss)
        finally:os.close(fd)
    except (OSError,ValueError,IndexError,KeyError):pass
    return result


def worker(root,sid,session,previous=None):
    owner = session.get('identity')
    resources = process(owner)
    result = dict(execution_id=public_id(sid),process=resources,
                  heartbeat=dict(status='UNKNOWN',counter=None,age_seconds=None))
    checkpoint = previous
    try:
        if not valid_id(sid) or session.get('directory')!=str(root/'roles'/sid):raise ValueError('unanchored worker')
        flags = os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        with contextlib.ExitStack() as stack:
            parent = os.open(root,flags);stack.callback(os.close,parent)
            roles = os.open('roles',flags,dir_fd=parent);stack.callback(os.close,roles)
            directory = os.open(sid,flags,dir_fd=roles);stack.callback(os.close,directory)
            value = read_json(directory,'worker-heartbeat.json',4096)
        if set(value)!={'schema_version','kind','context','identity','counter','monotonic_seconds'} or value['schema_version']!='1.0' or value['kind']!='WORKER_HEARTBEAT':raise ValueError('invalid heartbeat')
        context,binding = value['context'],session.get('release_binding') or {}
        if (not context_valid(context) or context['session']!=sid or context['generation']!=session.get('generation')
                or context['request_sha256']!=binding.get('request_sha256') or context['candidate_sha256']!=binding.get('candidate_sha256')
                or binding.get('identity')!=owner or binding.get('session')!=sid or binding.get('generation')!=context['generation']
                or not identity_valid(owner) or value['identity']!=owner or resources['status']!='KNOWN'):raise ValueError('unbound heartbeat')
        counter,issued = value['counter'],value['monotonic_seconds']
        now = time.monotonic()
        if type(counter) is not int or not 0<counter<2**63 or not number(issued) or issued>now:raise ValueError('invalid heartbeat clock')
        lineage = sha(dict(context=context,identity=owner))
        confirmed = False
        if previous and previous['binding']==lineage:
            if set(previous)!={'binding','counter','monotonic_seconds','confirmed'} or type(previous['confirmed']) is not bool:
                raise ValueError('invalid heartbeat witness')
            if counter<previous['counter'] or issued<previous['monotonic_seconds'] or counter==previous['counter'] and issued!=previous['monotonic_seconds'] or counter>previous['counter'] and issued<=previous['monotonic_seconds']:
                raise ValueError('heartbeat regression')
            confirmed = previous['confirmed'] or counter>previous['counter']
        age = now-issued
        if confirmed:result['heartbeat']=dict(status='FRESH' if age<=15 else 'STALE',counter=counter,age_seconds=age)
        checkpoint = dict(binding=lineage,counter=counter,monotonic_seconds=issued,confirmed=confirmed)
    except (OSError,ValueError,TypeError,KeyError,IndexError,RecursionError,OverflowError):pass
    return result,checkpoint
