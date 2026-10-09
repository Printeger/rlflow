"""Actual temporary Linux locks, no lease, worker, model or GPU grant."""
import os
import fcntl
import select
import signal
from pathlib import Path
import subprocess
import sys

import pytest

from rlflow.hybrid_workspace_kernel import DirectoryHold,LOCAL_FILESYSTEMS
from rlflow.store import Conflict


@pytest.fixture
def workspace(tmp_path):
    parent=tmp_path/'private';parent.mkdir(mode=0o700)
    path=parent/'candidate';path.mkdir(mode=0o700)
    return path


def test_actual_directory_lock_is_exclusive_and_close_is_idempotent(workspace):
    hold=DirectoryHold(workspace)
    try:
        value=hold.check();assert value['execution_enabled'] is False and value['filesystem'] in LOCAL_FILESYSTEMS
        assert not os.get_inheritable(hold._fd) and not os.get_inheritable(hold._parent_fd)
        with pytest.raises(Conflict):DirectoryHold(workspace)
    finally:hold.close()
    hold.close()
    with pytest.raises(Conflict,match='closed'):hold.check()
    another=DirectoryHold(workspace);another.close()


def test_independent_process_cannot_acquire_same_inode(workspace):
    hold=DirectoryHold(workspace)
    script='from rlflow.hybrid_workspace_kernel import DirectoryHold\nfrom rlflow.store import Conflict\nimport sys\ntry: DirectoryHold(sys.argv[1])\nexcept Conflict: sys.exit(23)\n'
    try:
        result=subprocess.run([sys.executable,'-c',script,str(workspace)],timeout=10,capture_output=True)
        assert result.returncode==23,result.stderr
    finally:hold.close()
    result=subprocess.run([sys.executable,'-c',script,str(workspace)],timeout=10,capture_output=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('change',['rename','symlink','parent_rename','mode'])
def test_original_path_chain_cannot_be_rebound(workspace,change):
    hold=DirectoryHold(workspace)
    try:
        if change=='rename':workspace.rename(workspace.with_name('old'));workspace.mkdir(mode=0o700)
        elif change=='symlink':
            workspace.rename(workspace.with_name('old'));workspace.symlink_to(workspace.with_name('old'),target_is_directory=True)
        elif change=='parent_rename':
            parent=workspace.parent;parent.rename(parent.with_name('old-parent'))
            parent.mkdir(mode=0o700);workspace.mkdir(mode=0o700)
        else:workspace.chmod(0o755)
        with pytest.raises(Conflict):hold.check()
    finally:hold.close()


def test_python_fork_invalidates_child_copy_without_unlocking_parent(workspace):
    hold=DirectoryHold(workspace);read,write=os.pipe();pid=None;reaped=False
    try:
        pid=os.fork()
        if pid==0:
            os.close(read)
            try:
                try:hold.check()
                except PermissionError:pass
                else:os._exit(2)
                try:DirectoryHold(workspace)
                except Conflict:os.write(write,b'blocked')
                else:os._exit(3)
                # A subsequent fork uses the reinitialized child registry
                # mutex, not a bound method of the inherited locked mutex.
                grandchild=os.fork()
                if grandchild==0:os._exit(0)
                if os.waitpid(grandchild,0)[1]!=0:os._exit(5)
                os._exit(0)
            except BaseException:os._exit(4)
        os.close(write);write=None
        assert select.select([read],[],[],10)[0],'fork fixture exceeded finite deadline'
        assert os.read(read,32)==b'blocked'
        assert os.waitpid(pid,0)[1]==0
        reaped=True
        assert hold.check()['execution_enabled'] is False
        with pytest.raises(Conflict):DirectoryHold(workspace)
    finally:
        os.close(read)
        if write is not None:os.close(write)
        if pid is not None and not reaped:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            os.waitpid(pid,0)
        hold.close()


def test_unsupported_mount_is_rejected_before_lock_admission(workspace,monkeypatch):
    import rlflow.hybrid_workspace_kernel as module
    hold=DirectoryHold(workspace);filesystem=hold.filesystem;hold.close()
    read=module._read_proc
    def network(path,limit):
        raw=read(path,limit)
        return raw.replace(' - '+filesystem+' ',' - nfs ') if path=='/proc/self/mountinfo' else raw
    monkeypatch.setattr(module,'_read_proc',network)
    with pytest.raises(Conflict,match='direct local'):DirectoryHold(workspace)


def test_subtree_mount_root_cannot_hide_physical_ancestors(workspace,monkeypatch):
    import rlflow.hybrid_workspace_kernel as module
    read=module._read_proc
    def subtree(path,limit):
        raw=read(path,limit)
        if path!='/proc/self/mountinfo':return raw
        lines=[]
        for line in raw.splitlines():
            prefix,separator,suffix=line.partition(' - ');fields=prefix.split()
            fields[3]='/disposable-bind-subtree';lines.append(' '.join(fields)+separator+suffix)
        return '\n'.join(lines)
    monkeypatch.setattr(module,'_read_proc',subtree)
    with pytest.raises(Conflict,match='mount root'):DirectoryHold(workspace)


def test_partial_close_failure_retains_actual_lock_until_explicit_cleanup(workspace,monkeypatch):
    import rlflow.hybrid_workspace_kernel as module
    hold=DirectoryHold(workspace);close=module.os.close;original=hold._fd
    def fault(fd):
        if fd==original:raise OSError('disposable fixture close fault')
        close(fd)
    try:
        monkeypatch.setattr(module.os,'close',fault)
        with pytest.raises(Conflict,match='cleanup failed'):hold.close()
        assert module._live[id(hold)] is hold and hold._fd==original
        with pytest.raises(Conflict,match='partially closed'):hold.check()
        with pytest.raises(Conflict):DirectoryHold(workspace)
    finally:
        monkeypatch.undo();hold.close()
    next_hold=DirectoryHold(workspace);next_hold.close()


def test_second_dup_failure_does_not_leak_constructor_fds(workspace,monkeypatch):
    import rlflow.hybrid_workspace_kernel as module
    count=[0];dup=module.os.dup;before=len(os.listdir('/proc/self/fd'));registered=len(module._live)
    def fail_second(fd):
        count[0]+=1
        if count[0]==2:raise OSError('disposable fixture dup fault')
        return dup(fd)
    monkeypatch.setattr(module.os,'dup',fail_second)
    with pytest.raises(Conflict):DirectoryHold(workspace)
    assert len(os.listdir('/proc/self/fd'))==before and len(module._live)==registered


@pytest.mark.parametrize('loss',['unlock','reopen'])
def test_actual_flock_loss_is_not_hidden_by_same_inode(workspace,loss):
    hold=DirectoryHold(workspace)
    try:
        if loss=='unlock':fcntl.flock(hold._fd,fcntl.LOCK_UN)
        else:
            fd=hold._fd;os.close(fd)
            reopened=os.open(workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
            if reopened!=fd:os.dup2(reopened,fd,inheritable=False);os.close(reopened)
        with pytest.raises(Conflict,match='flock'):hold.check()
        # Inspection did not silently reacquire a replacement lock.
        another=DirectoryHold(workspace);another.close()
    finally:hold.close()


def test_constructor_failure_retains_uncertain_hold_and_attempts_both_closes(workspace,monkeypatch):
    import rlflow.hybrid_workspace_kernel as module
    original_check=DirectoryHold.check;close=module.os.close;captured=[];attempted=[]
    def fail_check(self):
        captured.append(self)
        raise Conflict('disposable constructor verification fault')
    def fail_close(fd):
        attempted.append(fd)
        if captured and fd==captured[0]._fd:raise OSError('disposable close fault')
        close(fd)
    monkeypatch.setattr(DirectoryHold,'check',fail_check);monkeypatch.setattr(module.os,'close',fail_close)
    try:
        with pytest.raises(Conflict,match='constructor verification'):DirectoryHold(workspace)
        hold=captured[0]
        assert module._live[id(hold)] is hold and not hold._closed
        assert hold._parent_fd is None and hold._fd in attempted
        monkeypatch.setattr(DirectoryHold,'check',original_check)
        with pytest.raises(Conflict):DirectoryHold(workspace)
    finally:
        monkeypatch.undo()
        for hold in captured:hold.close()


def test_ancestor_close_failure_attempts_remaining_fds_and_is_reachable(workspace,monkeypatch):
    import rlflow.hybrid_workspace_kernel as module
    close=module.os.close;target=[];attempted=[]
    def fail(fd):
        attempted.append(fd)
        if target and fd==target[0]:raise OSError('disposable ancestor close fault')
        close(fd)
    monkeypatch.setattr(module.os,'close',fail)
    try:
        with pytest.raises(Conflict,match='ancestor cleanup'):
            with module._chain(workspace) as (fds,_):target.append(fds[-1]);expected=list(fds)
        assert all(fd in attempted for fd in expected)
        assert target[0] in module._orphaned_fds
    finally:
        monkeypatch.undo();module.cleanup_quarantine()


def test_two_actual_processes_have_one_winner(workspace):
    script=('from rlflow.hybrid_workspace_kernel import DirectoryHold\n'
        'from rlflow.store import Conflict\nimport sys\n'
        'try: hold=DirectoryHold(sys.argv[1])\n'
        'except Conflict: print("BLOCKED",flush=True);sys.exit(23)\n'
        'print("HELD",flush=True)\nsys.stdin.read(1)\nhold.close()\n')
    processes=[]
    try:
        for _ in range(2):
            processes.append(subprocess.Popen([sys.executable,'-c',script,str(workspace)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,close_fds=True))
        states=[]
        for process in processes:
            assert select.select([process.stdout],[],[],10)[0],'competition fixture timed out'
            states.append(process.stdout.readline().strip())
        assert sorted(states)==['BLOCKED','HELD']
        for process,state in zip(processes,states):
            if state=='HELD':process.stdin.write('x');process.stdin.flush()
            assert process.wait(timeout=10)==(0 if state=='HELD' else 23)
    finally:
        for process in processes:
            if process.poll() is None:process.kill();process.wait(timeout=10)
            for stream in (process.stdin,process.stdout,process.stderr):stream.close()


def test_sigkill_releases_kernel_lock_without_restoring_capability(workspace):
    script=('from rlflow.hybrid_workspace_kernel import DirectoryHold\nimport sys\n'
        'hold=DirectoryHold(sys.argv[1])\nprint("HELD",flush=True)\nsys.stdin.read(1)\n')
    process=subprocess.Popen([sys.executable,'-c',script,str(workspace)],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,close_fds=True)
    try:
        assert select.select([process.stdout],[],[],10)[0],'crash fixture timed out'
        assert process.stdout.readline().strip()=='HELD'
        with pytest.raises(Conflict):DirectoryHold(workspace)
        process.kill();assert process.wait(timeout=10)==-signal.SIGKILL
        # Fresh acquisition only, not adoption of any historical JSON/FD.
        new=DirectoryHold(workspace);new.close()
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)
        for stream in (process.stdin,process.stdout,process.stderr):stream.close()
