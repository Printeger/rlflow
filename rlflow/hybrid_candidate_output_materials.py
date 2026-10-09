"""Original-cap finite application: exact one file, no generic writer/shell."""
from contextlib import contextmanager
import os
import time

from .files import stamp
from .hybrid_engineering_patch import TARGET,BEFORE,AFTER,CASES
from .hybrid_working_plan_materials import _inventory,_tree,_private
from .hybrid_fixture_materials import _deadline,_verify_inventory
from .store import Conflict,canonical


def metadata(root,inventory):
    files,directories,chain=inventory
    return {'files':{name:tuple(row['stamp']) for name,row in files.items()},
        'directories':{str(row['path'].relative_to(root)):tuple(row['stamp']) for row in directories},
        'chain':tuple(tuple(row) for row in chain)}


class CandidateOutputMaterial:
    """Created only by trusted core with original Runtime/Working objects.

    Old graph stamps remain private in this actual object. After write, only
    original target content timestamps/size may differ. Reopening witnesses
    does not adopt a caller's after path or reconstruct a writer on restart.
    """
    def __init__(self,runtime,lease):
        with runtime.pool._lock:
            self._initialize(runtime,lease)
            if len(runtime._candidate_materials)>=32:
                raise Conflict('finite original candidate material capacity reached')
            runtime._candidate_materials[id(self)]=self

    def _initialize(self,runtime,lease):
        runtime._actual();attempt=runtime._issued(lease)
        if attempt['engineering_grant'] is None:raise PermissionError('original engineering attempt required')
        runtime._check_terminal(attempt)
        self.runtime,self.attempt=runtime,attempt
        self.observation=attempt['observation'];self.bundle=attempt['bundle']
        self.slot,_=runtime.workspace.working._slot(self.observation)
        self.root=self.slot['copy'].path;self.plan_root=self.bundle.path
        self.limit=runtime.workspace.preparation.builder.byte_limit
        self.write_entered=False;self.fd=None;self.closed=False
        with runtime.plans.builder._witness(self.bundle) as witness:
            self.base_meta=metadata(self.root,witness.candidate_inventory)
            self.plan_meta=metadata(self.plan_root,witness.material_inventory)
            self.base_tree=_tree(self.root,witness.candidate_inventory,self.limit,witness.deadline)
            target=witness.candidate_inventory[0].get(TARGET)
            if target is None:raise Conflict('original candidate output target missing')
            self.target_stamp=tuple(target['stamp']);self.target_identity=list(self.target_stamp[:2])
            fd=os.open(target['path'].name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=target['parent_fd'])
            try:
                if stamp(os.fstat(fd))!=self.target_stamp or os.pread(fd,len(BEFORE)+1,0)!=BEFORE:
                    raise Conflict('original candidate before bytes changed')
            finally:os.close(fd)
            witness.check()

    def check_hold(self,*,receipt=False):
        self.runtime._actual()
        if self.runtime._candidate_materials.get(id(self)) is not self:
            raise PermissionError('actual original candidate material required')
        current,_=self.runtime.workspace.working._slot(self.observation)
        if current is not self.slot:
            raise Conflict('candidate output original Working slot changed')
        working=self.runtime.workspace.working
        if receipt:
            if not self.write_entered or not self.closed or self.fd is not None:
                raise PermissionError('receipt-only original write and close proof required')
            # Safety readback does not renew an expired write authority.
            working._owner_check();working._namespace_check()
            if self.slot['hold'].check()!=self.slot['binding']['kernel']:
                raise Conflict('candidate receipt original Kernel changed')
        else:working.check(self.observation)

    @contextmanager
    def witness(self,*,after=False,effect=False):
        self.check_hold(receipt=after);deadline=time.monotonic()+30
        with _inventory(self.plan_root,deadline) as plan,_inventory(self.root,deadline) as candidate:
            self.check_graph(plan,candidate,deadline,after=after)
            yield plan,candidate,deadline
            final_after=after or effect and self.write_entered
            self.check_graph(plan,self.after_inventory(candidate) if final_after else candidate,deadline,after=final_after)

    def after_inventory(self,candidate):
        files,directories,chain=candidate
        item=files[TARGET];current=stamp(item['path'].lstat())
        if current[:4]!=self.target_stamp[:4]:raise Conflict('candidate output target rebound')
        return {**files,TARGET:{**item,'stamp':current}},directories,chain

    def check_graph(self,plan,candidate,deadline,*,after):
        _deadline(deadline);self.check_hold(receipt=after)
        if metadata(self.plan_root,plan)!=self.plan_meta:raise Conflict('candidate output original plan graph changed')
        now=metadata(self.root,candidate)
        if set(now['files'])!=set(self.base_meta['files']) or now['directories']!=self.base_meta['directories'] or now['chain']!=self.base_meta['chain']:
            raise Conflict('candidate output original directory/ancestor graph changed')
        for name,original in self.base_meta['files'].items():
            actual=now['files'][name]
            if (name!=TARGET or not after) and actual!=original:
                raise Conflict('candidate output non-target or before identity changed')
            if name==TARGET and after and actual[:4]!=original[:4]:
                raise Conflict('candidate output target inode/mode/link changed')
        if after:
            if not self.write_entered:raise PermissionError('actual original write attempt required for after view')
            self._read_target(candidate,AFTER,deadline)
        else:self._read_target(candidate,BEFORE,deadline)
        _verify_inventory(self.plan_root,*plan,deadline);_verify_inventory(self.root,*candidate,deadline)

    def _read_target(self,inventory,expected,deadline):
        item=inventory[0][TARGET]
        fd=os.open(item['path'].name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=item['parent_fd'])
        try:
            info=os.fstat(fd);_private(info)
            actual=os.pread(fd,len(expected)+1,0)
            if stamp(info)!=item['stamp'] or actual!=expected or stamp(os.fstat(fd))!=item['stamp']:
                raise Conflict('candidate output actual target content differs')
        finally:os.close(fd)
        _deadline(deadline)
        return actual

    def begin_fd(self,candidate):
        with self.runtime.pool._lock:
            self.check_hold()
            self._begin_fd(candidate)

    def _begin_fd(self,candidate):
        if self.fd is not None or self.write_entered or self.closed:raise Conflict('candidate output original write fd already used')
        item=candidate[0][TARGET]
        fd=os.open(item['path'].name,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=item['parent_fd'])
        try:
            if stamp(os.fstat(fd))!=self.target_stamp or os.pread(fd,len(BEFORE)+1,0)!=BEFORE:
                raise Conflict('candidate output actual write inode/before changed')
            self.fd=fd
        except BaseException:os.close(fd);raise

    def apply_once(self,guard):
        with self.runtime.pool._lock:
            from .hybrid_candidate_output_service import _Guard
            if type(guard) is not _Guard or guard.row['material'] is not self or guard.receipt:
                raise PermissionError('actual live core candidate guard required')
            self.check_hold()
            self._apply_once(guard)

    def _apply_once(self,guard):
        if self.fd is None or self.closed:raise PermissionError('actual original candidate write fd required')
        if self.write_entered:raise Conflict('candidate output original write UNKNOWN; reconcile only')
        if stamp(os.fstat(self.fd))!=self.target_stamp or os.pread(self.fd,len(BEFORE)+1,0)!=BEFORE:
            raise Conflict('candidate output last actual write boundary changed')
        guard.check();guard.last_effect()
        self.write_entered=True
        # One bounded syscall, flag precedes uncertain outcome. Never replay.
        written=os.pwrite(self.fd,AFTER,0)
        if written!=len(AFTER):raise Conflict('candidate output partial write UNKNOWN; no automatic rewrite')
        os.fsync(self.fd)

    def close_fd(self):
        with self.runtime.pool._lock:
            self.runtime._actual()
            if self.runtime._candidate_materials.get(id(self)) is not self:
                raise PermissionError('actual original candidate material required')
            self._close_fd()

    def _close_fd(self):
        if self.fd is None:
            if self.closed:return
            raise Conflict('candidate output missing actual close witness')
        info=os.fstat(self.fd)
        if (info.st_dev,info.st_ino)!=tuple(self.target_identity):raise Conflict('candidate output write FD identity unknown')
        os.fsync(self.fd);os.close(self.fd);self.fd=None;self.closed=True

    def capture(self,candidate,deadline):
        if not self.write_entered or not self.closed or self.fd is not None:
            raise Conflict('candidate output actual write and FD closure required')
        actual=self._read_target(candidate,AFTER,deadline)
        # Actual file bytes were exactly checked before running fixed code.
        namespace={};exec(actual,namespace)
        tests=[{'left':a,'right':b,'expected':a+b,'actual':namespace['add'](a,b)} for a,b in CASES]
        if any(row['actual']!=row['expected'] for row in tests):raise Conflict('candidate output actual fixed tests failed')
        tree=_tree(self.root,candidate,self.limit,deadline)
        return tree,tests
