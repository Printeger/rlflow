"""Inherited CPU task confinement for the future original local Runner owner.

This kernel substrate is NOT an ExecutionLease, release gate, cgroup owner,
disk quota, model capability or permission to start a product task. The caller
must create and verify its original bounded cgroup BEFORE installing this
restriction, close other descriptors, and obtain original Core release.
Do not substitute this module for the existing denied general start paths.
"""
import ctypes
import errno
import os
import platform
import stat


def close_keeper_producers():
    """Irreversible no-fork/no-exec fence on the trusted, post-fork keeper.

    Install ONLY after its confined task has already forked. This deliberately
    does not restrict that original task's existing fork/exec capabilities.
    It is not a task sandbox or proof that the manager scope is terminal.
    """
    if platform.machine()!='x86_64' or len(os.listdir('/proc/self/task'))!=1:
        raise RuntimeError('single-threaded verified x86_64 keeper required')
    libc=ctypes.CDLL(None,use_errno=True)
    class Filter(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),
                  ('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_=[('length',ctypes.c_ushort),('filters',ctypes.POINTER(Filter))]
    rows=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(6,0,0,0x80000000),
          (0x20,0,0,0),(0x45,0,1,0x40000000),(6,0,0,0x80000000)]
    # All process/thread creation and image replacement, not just os.fork.
    for number in (56,57,58,59,322,425,426,427,435):
        rows.extend([(0x15,0,1,number),(6,0,0,0x50000|errno.EPERM)])
    # Unknown future syscall interfaces require requalification.
    rows.extend([(0x35,0,1,450),(6,0,0,0x50000|errno.EPERM),(6,0,0,0x7fff0000)])
    filters=(Filter*len(rows))(*(Filter(*row) for row in rows))
    program=Program(len(rows),filters)
    for args in ((38,1,0,0,0),(22,2,ctypes.byref(program),0,0)):
        result=libc.prctl(*args)
        if result!=0:raise OSError(ctypes.get_errno(),'original keeper producer fence failed')
    return {'new_processes':'DENIED','new_threads':'DENIED','exec':'DENIED'}


def confine(executable_fds, readonly_fds, work_fd):
    """Restrict this process and all future descendants; failures must be fatal.

    Inputs are original held O_PATH descriptors, not subsequently reopened
    paths. No outside socket can be created/connected, cgroup files cannot be
    written, and outside processes cannot be signalled or ptraced. Fork/exec
    and setsid remain available: the original cgroup, NOT a process group,
    must contain and stop descendants. Existing outside FDs are the caller's
    responsibility; neither Landlock nor seccomp retroactively revokes them.
    The trusted gate must whitelist its environment and run single-threaded
    before executing any task code. This function does not sanitize secrets.
    """
    if platform.machine() != 'x86_64':
        raise RuntimeError('local CPU sandbox requires verified x86_64 ABI')
    if len(os.listdir('/proc/self/task')) != 1:
        raise RuntimeError('single-threaded original CPU gate required')
    if (type(executable_fds) is not tuple or not 1 <= len(executable_fds) <= 16 or
            type(readonly_fds) is not tuple or len(readonly_fds) > 32 or
            any(type(fd) is not int or fd < 0 for fd in (*executable_fds, *readonly_fds, work_fd))):
        raise TypeError('bounded original held descriptor set required')
    for fd in executable_fds:
        value = os.fstat(fd)
        if not stat.S_ISREG(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise RuntimeError('root-owned immutable executable inode required')
    work = os.fstat(work_fd)
    if (not stat.S_ISDIR(work.st_mode) or work.st_uid != os.geteuid() or
            stat.S_IMODE(work.st_mode) != 0o700):
        raise RuntimeError('original private CPU task directory required')
    libc = ctypes.CDLL(None, use_errno=True)

    def check(result):
        if result < 0:
            raise OSError(ctypes.get_errno(), 'local CPU sandbox restriction failed')
        return result

    if check(libc.syscall(444, 0, 0, 1)) < 3:
        raise RuntimeError('Landlock truncate protection required')

    class Ruleset(ctypes.Structure):
        _fields_ = [('rights', ctypes.c_uint64)]

    class Beneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('rights', ctypes.c_uint64), ('fd', ctypes.c_int)]

    handled = (1 << 15) - 1
    ruleset = Ruleset(handled)
    descriptor = check(libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0))
    opened = []
    try:
        entries = [(fd, 1 | 4) for fd in executable_fds]
        for fd in readonly_fds:
            value = os.fstat(fd)
            if not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode)):
                raise RuntimeError('regular file/directory CPU input required')
            entries.append((fd, 4 | (8 if stat.S_ISDIR(value.st_mode) else 0)))
        # No executable creation, device node, FIFO or Unix socket creation.
        entries.append((work_fd, handled & ~(1 | (1 << 6) | (1 << 9) | (1 << 10) | (1 << 11))))
        for path in ('/dev/null', '/dev/zero', '/dev/urandom'):
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            opened.append(fd)
            entries.append((fd, 2 | 4))
        for fd, rights in entries:
            rule = Beneath(rights, fd)
            check(libc.syscall(445, descriptor, 1, ctypes.byref(rule), 0))
        check(libc.prctl(38, 1, 0, 0, 0))
        check(libc.syscall(446, descriptor, 0))
    finally:
        for fd in opened:
            os.close(fd)
        os.close(descriptor)

    # Architecture fence rejects other ABI/x32 calls before their numbers can
    # alias allowed x86_64 operations. All restrictions survive fork and exec.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                   ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]

    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]

    rows = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xc000003e), (6, 0, 0, 0x80000000),
            (0x20, 0, 0, 0), (0x45, 0, 1, 0x40000000), (6, 0, 0, 0x80000000)]
    # socket/socketpair/connect/send*/recv*; signals, tracing, alternate IO,
    # namespace/mount manipulation, host IPC, kernel keyrings/perf/BPF.
    # Landlock ABI3 does NOT mediate chmod/chown/time/xattr metadata writes:
    # these must be denied independently, including outside unreadable files.
    denied = (41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55,
              62, 101, 129, 155, 161, 165, 166, 169, 175, 176, 200, 234, 297,
              246, 248, 249, 250, 272, 298, 299, 304, 307, 308, 310, 311,
              313, 321, 323, 424, 425, 426, 427, 438, 440, 448,
              29, 30, 31, 64, 65, 66, 67, 68, 69, 70, 71,
              134, 135, 141, 142, 144, 159, 164, 203, 314,
              16, 90, 91, 92, 93, 94, 132, 188, 189, 190, 197, 198, 199,
              235, 240, 241, 242, 243, 244, 245, 251, 260, 261, 268, 280)
    for number in denied:
        rows.extend([(0x15, 0, 1, number), (6, 0, 0, 0x50000 | errno.EPERM)])
    # Async file notification can signal another same-UID process without any
    # kill syscall. Preserve ordinary descriptor/nonblocking operations, never
    # permit assignment of an async owner, signal, dnotify, or O_ASYNC enable.
    fcntl = [(0x20, 0, 0, 24)]
    for command in (8, 10, 15, 1024, 1026):  # Async ownership/lease/dnotify.
        fcntl.extend([(0x15, 0, 1, command), (6, 0, 0, 0x50000 | errno.EPERM)])
    fcntl.extend([(0x15, 0, 3, 4), (0x20, 0, 0, 32),  # F_SETFL flags.
                  (0x45, 0, 1, 0x2000), (6, 0, 0, 0x50000 | errno.EPERM),
                  (6, 0, 0, 0x7fff0000)])
    rows.append((0x15, 0, len(fcntl), 72))
    rows.extend(fcntl)
    rows.extend([# Future syscall ABI needs explicit requalification. Includes
                 # fchmodat2/new xattr-at/namespace query interfaces.
                 (0x35, 0, 1, 450), (6, 0, 0, 0x50000 | errno.EPERM),
                 (0x15, 0, 1, 435), (6, 0, 0, 0x50000 | errno.ENOSYS),
                 # clone namespace flags; normal process/thread clone allowed.
                 (0x15, 0, 4, 56), (0x20, 0, 0, 16),
                 (0x45, 0, 1, 0x7e020000), (6, 0, 0, 0x50000 | errno.EPERM),
                 (6, 0, 0, 0x7fff0000),
                 # prlimit64: allow current process only (pid=0).
                 (0x15, 0, 4, 302), (0x20, 0, 0, 16),
                 (0x15, 1, 0, 0), (6, 0, 0, 0x50000 | errno.EPERM),
                 (6, 0, 0, 0x7fff0000),
                 (6, 0, 0, 0x7fff0000)])
    filters = (Filter * len(rows))(*(Filter(*row) for row in rows))
    program = Program(len(rows), filters)
    check(libc.prctl(22, 2, ctypes.byref(program), 0, 0))
    return {'landlock': True, 'seccomp': True, 'no_new_privs': True,
            'network': 'DENIED', 'gpu': 'DENIED',
            'containment': 'REQUIRES_ORIGINAL_CGROUP_OWNER',
            'disk_quota': 'NOT_PROVIDED'}
