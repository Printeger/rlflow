"""Original Working plan bytes, never runtime or standalone write permission.

The fixed core owner binds the expected seal into an original immutable INTENT
before native publication and a second nonexecuting READY fact.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time
import uuid

from .files import stamp, relative_name
from .hybrid_goals import digest
from .hybrid_runtime_boundary import _held_chain, directory_chain
from .hybrid_fixture_materials import _deadline, _verify_inventory
from .isolation import _render_codex_policy, CODEX
from .store import canonical, Conflict

MAX_FILES=4096
MAX_BYTES=256*1024**2
ARTIFACT_BYTES=16*1024**2
FILES=('plan.json','packet.json','result.schema.json','command-plan.json',
       'control/result.json.models.json','control/result.json.mcp.json')


@dataclass(frozen=True,eq=False)
class WorkingExecutionPlan:
    id: str
    raw: bytes


@dataclass(frozen=True,eq=False)
class WorkingPlanBundle:
    id: str
    raw: bytes
    stage_path: Path
    path: Path


@dataclass(frozen=True,eq=False)
class _Seed:
    id: str
    raw: bytes
    token: object
    observation: object
    preparation: tuple


@dataclass(frozen=True,eq=False)
class _WorkingPlanWitness:
    """Borrowed original descriptor graphs, NEVER a persistence permit."""
    builder: object
    bundle: object
    path: Path
    candidate: Path
    material_inventory: tuple
    candidate_inventory: tuple
    deadline: float
    thread: int

    def check(self):self.builder._check_witness(self)


def _private(info,directory=False):
    if ((not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode)) or
            info.st_uid!=os.getuid() or (info.st_mode&0o077 if directory else stat.S_IMODE(info.st_mode)!=0o600) or
            not directory and info.st_nlink!=1):
        raise Conflict('Working plan requires original private regular entries')


@contextmanager
def _inventory(root,deadline):
    """Complete finite descriptor graph, including extra/empty directories."""
    root=Path(root);files={};directories=[];names_bytes=0;count=0
    with _held_chain(root) as (chain_fds,chain),ExitStack() as cleanup:
        info=os.fstat(chain_fds[-1]);_private(info,True)
        directories.append({'path':root,'fd':chain_fds[-1],'stamp':stamp(info),'parent_fd':None})
        stack=[(root,chain_fds[-1],0)]
        while stack:
            path,parent,depth=stack.pop();_deadline(deadline)
            if depth>64:raise Conflict('Working plan inventory depth exceeded')
            with os.scandir(parent) as entries:
                for entry in entries:
                    _deadline(deadline);count+=1
                    if count>MAX_FILES*2:raise Conflict('Working plan inventory entry count exceeded')
                    target=path/entry.name;name=str(target.relative_to(root));relative_name(name)
                    names_bytes+=len(os.fsencode(name))
                    if names_bytes>1024**2 or len(os.fsencode(name))>4000:
                        raise Conflict('Working plan inventory name budget exceeded')
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        _private(info,True)
                        if len(directories)>=MAX_FILES:raise Conflict('Working plan directory count exceeded')
                        fd=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
                        cleanup.callback(os.close,fd)
                        if stamp(os.fstat(fd))!=stamp(info):raise Conflict('Working original directory changed')
                        directories.append({'path':target,'fd':fd,'stamp':stamp(info),'parent_fd':parent})
                        stack.append((target,fd,depth+1))
                    else:
                        _private(info)
                        if len(files)>=MAX_FILES:raise Conflict('Working plan file count exceeded')
                        files[name]={'path':target,'parent_fd':parent,'stamp':stamp(info)}
        _verify_inventory(root,files,directories,chain,deadline)
        yield files,directories,chain


def _hash_file(item,remaining,deadline):
    _deadline(deadline)
    fd=os.open(item['path'].name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=item['parent_fd'])
    try:
        before=os.fstat(fd);_private(before)
        if stamp(before)!=item['stamp'] or not 0<=before.st_size<=remaining:
            raise Conflict('Working original captured file or byte budget differs')
        hashed=hashlib.sha256();size=0
        while True:
            _deadline(deadline);chunk=os.read(fd,min(65536,remaining-size+1))
            if not chunk:break
            size+=len(chunk)
            if size>remaining:raise Conflict('Working plan file byte budget exceeded')
            hashed.update(chunk)
        after=os.fstat(fd);current=os.stat(item['path'].name,dir_fd=item['parent_fd'],follow_symlinks=False)
        if size!=before.st_size or stamp(after)!=item['stamp'] or stamp(current)!=item['stamp']:
            raise Conflict('Working original file changed during hash')
        _deadline(deadline)
        return size,'sha256:'+hashed.hexdigest()
    finally:os.close(fd)


def _tree(root,inventory,limit,deadline):
    files,directories,chain=inventory;rows=[];total=0
    if not files:raise Conflict('Working candidate must have finite source files')
    for name in sorted(files):
        size,hashed=_hash_file(files[name],limit-total,deadline);total+=size
        rows.append({'name':name,'bytes':size,'sha256':hashed,'mode':0o600})
    value={'files':rows,'directories':sorted(str(item['path'].relative_to(root)) for item in directories),
           'total_bytes':total}
    _verify_inventory(root,files,directories,chain,deadline)
    return {**value,'tree_hash':digest(value),'execution_enabled':False}


def _write_at(parent,name,raw,deadline):
    _deadline(deadline)
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
    try:
        rest=memoryview(raw)
        while rest:
            _deadline(deadline);count=os.write(fd,rest[:65536])
            if count<=0:raise Conflict('Working plan material write failed')
            rest=rest[count:]
        os.fsync(fd);_deadline(deadline)
    finally:os.close(fd)


class WorkingPlanMaterialBuilder:
    def __init__(self,owner):
        from .hybrid_working_plan_service import WorkingPlanService
        if type(owner) is not WorkingPlanService or getattr(owner.store,'_hybrid_working_plan_service',None) is not owner:
            raise TypeError('fixed original Working plan material owner required')
        self.owner=owner;self._lock=threading.RLock();self._issued={};self._attempts={};self._witnesses={};self._rebases={}
        installation=owner.installation.builder;installation._check_physical()
        parent=installation._roots['bootstrap'];leaf='working_plans_'+uuid.uuid4().hex
        with _held_chain(parent) as (fds,chain):
            if chain!=installation._chains['bootstrap']:raise Conflict('original plan control parent differs')
            os.mkdir(leaf,0o700,dir_fd=fds[-1]);os.fsync(fds[-1])
        self.root=parent/leaf;self._chain=directory_chain(self.root)

    def _check(self):
        self.owner.installation.builder._check_physical()
        if directory_chain(self.root)!=self._chain:raise Conflict('original Working plan control rebound')
        with _held_chain(self.root) as (fds,_):_private(os.fstat(fds[-1]),True)

    def _seed(self,seed):
        if type(seed) is not _Seed or self.owner._seeds.get(seed.id) is not seed:
            raise PermissionError('actual original Working plan seed required')
        working,_=self.owner.workspace.working._slot(seed.observation)
        self.owner.workspace.working.check(seed.observation)
        return working,json.loads(seed.raw)

    @staticmethod
    def _writes(proposal,candidate,role,inventory):
        if role!='Engineer':return []
        def name(value):
            value=value[:-1] if value.endswith('/') else value
            relative_name(value)
            if '\x00' in value:raise Conflict('invalid Working approved scope path')
            return value
        writes=[name(value) for value in proposal['scope']['writable_paths']]
        protected=[name(value) for value in proposal['scope']['protected_paths']]
        if len(writes)>128 or len(set(writes))!=len(writes):raise Conflict('bounded unique Working writes required')
        files,directories,_=inventory
        names=set(files)|{str(row['path'].relative_to(candidate)) for row in directories}
        for writable in writes:
            if writable not in names or any(writable==p or writable.startswith(p+'/') or p.startswith(writable+'/') for p in protected):
                raise Conflict('actual Working write mapping absent or protected')
        return [str(candidate/value) for value in writes]

    def build(self,seed):
        with self._lock:
            self._check();working,value=self._seed(seed);deadline=time.monotonic()+30
            if seed.id in self._issued:return self.verify(self._issued[seed.id]['bundle'])['bundle']
            if seed.id in self._attempts:raise Conflict('original Working plan attempt remains blocked; no remint')
            if len(self._attempts)>=128:raise Conflict('Working plan material capacity reached')
            stage=self.root/('.preparing-'+seed.id);destination=self.root/seed.id
            self._attempts[seed.id]={'stage':stage,'destination':destination}
            candidate=working['copy'].path
            with _inventory(candidate,deadline) as inventory:
                tree=_tree(candidate,inventory,self.owner.workspace.preparation.builder.byte_limit,deadline)
                old_plan=value['preparation_plan'];role=old_plan['packet']['role'];profile=old_plan['profile']
                writes=self._writes(value['proposal'],candidate,role,inventory)
                packet={**old_plan['packet'],'candidate_snapshot_hash':tree['tree_hash']}
                # Read ONLY the original sealed model subset, not HOME/env/cache.
                from .execution_adapter import _digest
                from .hybrid_fixture_materials import _read_bounded
                bundle=seed.preparation[2];model_file='control/result.json.models.json'
                adapter=self.owner.workspace.preparation.adapter
                original_plan,original_bundle=adapter._bundle(bundle)
                if original_plan is not seed.preparation[1] or adapter._seals.get(original_plan.id)!=original_bundle['seal']:
                    raise Conflict('original known published preparation model subset required')
                published=adapter.root/original_plan.id
                with _held_chain(published/'control') as (fds,chain):
                    for fd,name in ((fds[-2],''),(fds[-1],'control')):
                        info=os.fstat(fd)
                        if [info.st_dev,info.st_ino]!=original_bundle['seal']['directories'][name]:
                            raise Conflict('original published preparation directory differs')
                    captured=stamp(os.stat('result.json.models.json',dir_fd=fds[-1],follow_symlinks=False))
                    models=_read_bounded(published/model_file,ARTIFACT_BYTES,parent_fd=fds[-1],expected=captured,deadline=deadline)
                    if directory_chain(published/'control')!=chain:
                        raise Conflict('original published preparation chain differs')
                expected=original_bundle['seal']['manifest']['files'][model_file]
                if _digest(models)!=expected:raise Conflict('Working original prepared model subset differs')
                plan_value={'schema_version':'1.0','adapter':'codex-exec','sources':value['context'],
                    'packet':packet,'profile':profile,'role_definition':old_plan['role_definition'],
                    'result_schema':old_plan['result_schema'],'candidate':str(candidate),'working_tree':tree,
                    'write_roots':writes,'allowed_tools':value['proposal']['allowed_tools'],
                    'allowed_command_templates':value['proposal']['scope']['allowed_command_templates'],
                    'gates':old_plan['gates'],'execution_enabled':False,'release_enabled':False}
                plan=WorkingExecutionPlan(seed.id,canonical(plan_value))
                import sys
                argv,model_raw,mcp_raw=_render_codex_policy(role,str(candidate),str(destination/'scratch'),
                    str(destination/'result.schema.json'),str(destination/'control/result.json'),catalog=json.loads(models),
                    write_roots=writes,read_extra=[],execute_extra=[],memory_bytes=profile['memory_bytes'],
                    model=profile['model'],effort=profile['effort'],command_seconds=profile['command_seconds'],
                    codex=CODEX,python=sys.executable,
                    isolation_module=str(self.owner.material.release_path/'rlflow/isolation.py'))
                payload={'plan.json':plan.raw,'packet.json':canonical(packet),'result.schema.json':canonical(plan_value['result_schema']),
                    'command-plan.json':canonical({'argv':argv,'execution_enabled':False,'release_enabled':False}),
                    'control/result.json.models.json':model_raw,'control/result.json.mcp.json':mcp_raw}
                manifest={'plan_hash':digest(plan_value),'files':{name:_digest(raw) for name,raw in payload.items()},
                          'execution_enabled':False,'release_enabled':False}
                manifest_raw=canonical(manifest)
                if sum(map(len,payload.values()))+len(manifest_raw)>ARTIFACT_BYTES:
                    raise Conflict('Working plan material byte budget exceeded')
                with _held_chain(self.root) as (fds,chain),ExitStack() as cleanup:
                    if chain!=self._chain:raise Conflict('original Working plan material parent differs')
                    os.mkdir(stage.name,0o700,dir_fd=fds[-1])
                    root=os.open(stage.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1]);cleanup.callback(os.close,root)
                    for folder in ('control','scratch'):os.mkdir(folder,0o700,dir_fd=root)
                    control=os.open('control',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root);cleanup.callback(os.close,control)
                    scratch=os.open('scratch',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root);cleanup.callback(os.close,scratch)
                    for name,raw in payload.items():_write_at(control if name.startswith('control/') else root,Path(name).name,raw,deadline)
                    _write_at(root,'manifest.json',manifest_raw,deadline)
                    for fd in (scratch,control,root,fds[-1]):_deadline(deadline);os.fsync(fd)
                _verify_inventory(candidate,*inventory,deadline)
                self._check();self._seed(seed);_deadline(deadline)
                seal={'manifest':manifest,'manifest_hash':_digest(manifest_raw),
                    'directory_identity':directory_chain(stage)[-1],'parent_chain':self._chain,
                    'file_lengths':{name:len(raw) for name,raw in payload.items()}}
                raw=canonical({'plan_id':plan.id,'plan_hash':digest(plan_value),'seal':seal,
                    'execution_enabled':False,'release_enabled':False})
                bundle=WorkingPlanBundle(plan.id,raw,stage,destination)
                self._issued[plan.id]={'seed':seed,'plan':plan,'bundle':bundle,'raw':raw,'plan_raw':plan.raw,
                    'stage':stage,'destination':destination,'working_tree':tree}
            self.verify(bundle,_operation_deadline=deadline);_deadline(deadline)
            return bundle

    def _slot(self,bundle):
        if type(bundle) is not WorkingPlanBundle:raise PermissionError('original Working plan bundle required')
        entry=next((row for row in tuple(self._issued.values()) if row['bundle'] is bundle),None)
        if entry is None:raise PermissionError('actual issued Working plan bundle required')
        if (bundle.raw!=entry['raw'] or bundle.stage_path!=entry['stage'] or bundle.path!=entry['destination'] or
                bundle.id!=entry['plan'].id or entry['plan'].raw!=entry['plan_raw']):
            raise Conflict('original Working plan bundle fields differ')
        return entry

    def verify(self,bundle,*,_operation_deadline=None):
        with self._lock:
            deadline=time.monotonic()+30 if _operation_deadline is None else _operation_deadline
            _deadline(deadline)
            self._check();entry=self._slot(bundle);working,_=self._seed(entry['seed'])
            value=json.loads(bundle.raw);seal=value['seal']
            published=bundle.path.exists() or bundle.path.is_symlink()
            path=bundle.path if published else bundle.stage_path
            if published and (bundle.stage_path.exists() or bundle.stage_path.is_symlink()):
                raise Conflict('Working plan stage and published path both exist')
            if directory_chain(path)[-1]!=seal['directory_identity']:raise Conflict('original Working plan directory differs')
            with _inventory(path,deadline) as inventory, _inventory(working['copy'].path,deadline) as candidate_inventory:
                files,directories,chain=inventory
                if (set(files)!=set(FILES)|{'manifest.json'} or
                        {str(row['path'].relative_to(path)) for row in directories}!={'.','control','scratch'}):
                    raise Conflict('original closed Working plan material domain differs')
                total=0
                for name in sorted(files):
                    size,hashed=_hash_file(files[name],ARTIFACT_BYTES-total,deadline);total+=size
                    expected=seal['manifest_hash'] if name=='manifest.json' else seal['manifest']['files'][name]
                    if hashed!=expected or name!='manifest.json' and size!=seal['file_lengths'][name]:
                        raise Conflict('original Working plan expected material seal differs')
                _verify_inventory(path,*inventory,deadline)
                candidate=working['copy'].path
                if _tree(candidate,candidate_inventory,self.owner.workspace.preparation.builder.byte_limit,deadline)!=entry['working_tree']:
                    raise Conflict('current actual Working bytes differ from sealed plan')
                self._seed(entry['seed']);self._check()
                if ((bundle.path.exists() or bundle.path.is_symlink())!=published or
                        published and (bundle.stage_path.exists() or bundle.stage_path.is_symlink()) or
                        directory_chain(path)[-1]!=seal['directory_identity']):
                    raise Conflict('original Working plan publication path changed during verification')
                _verify_inventory(path,*inventory,deadline)
                _verify_inventory(candidate,*candidate_inventory,deadline)
                _deadline(deadline)
                return {'bundle':bundle,'plan':entry['plan'],'seal':seal,'execution_enabled':False,'release_enabled':False}

    def publish(self,bundle):
        self._slot(bundle)
        raise PermissionError('actual Working publication is reserved to its core owner')

    def _rebase_publication(self,witness,attempt):
        """Owner's original rename only; never recapture child/file stamps."""
        from .hybrid_installation_service import _RenameReceipt
        owner=self.owner;context=owner._context;guard=owner._active
        if (type(witness) is not _WorkingPlanWitness or self._witnesses.get(id(witness)) is not witness or
                witness.thread!=threading.get_ident() or owner._publication_active is not attempt or
                owner._publication_attempts.get(witness.bundle.id) is not attempt or
                attempt.get('witness') is not witness or type(attempt.get('receipt')) is not _RenameReceipt or
                not attempt['receipt'].succeeded or
                context is None or context.plan_witness is not witness or guard is None or
                guard.context is not context or guard.bundle is not witness.bundle or
                witness.path!=witness.bundle.stage_path or id(witness) in self._rebases):
            raise PermissionError('actual owner rename and original held graph required')
        _deadline(witness.deadline)
        bundle=witness.bundle;files,directories,chain=witness.material_inventory
        if (bundle.stage_path.exists() or bundle.stage_path.is_symlink() or
                directory_chain(bundle.path)!=chain):
            raise Conflict('original Working publication path identity differs')
        root=directories[0];info=os.fstat(root['fd']);_private(info,True)
        current=stamp(info)
        if current[:-1]!=root['stamp'][:-1] or stamp(bundle.path.lstat())!=current:
            raise Conflict('Working rename changed more than original root ctime')
        rebased_files={name:{**item,'path':bundle.path/item['path'].relative_to(witness.path)}
                       for name,item in files.items()}
        rebased_dirs=[{**item,'path':bundle.path/item['path'].relative_to(witness.path),
                       'stamp':current if index==0 else item['stamp']}
                      for index,item in enumerate(directories)]
        inventory=(rebased_files,rebased_dirs,chain)
        _verify_inventory(bundle.path,*inventory,witness.deadline)
        _verify_inventory(witness.candidate,*witness.candidate_inventory,witness.deadline)
        self._rebases[id(witness)]=(witness,attempt,bundle.path,inventory)
        witness.check()

    def _check_witness(self,witness):
        # NO Builder lock here: a build hashes outside writer while holding
        # Builder -> Working; a future writer already holds Working. Waiting
        # for Builder would invert that order. Registry/original slots are
        # identity checked, never replaced, and only this thread retires this
        # borrowed witness after its caller's owned writer has exited.
        if (type(witness) is not _WorkingPlanWitness or witness.builder is not self or
                self._witnesses.get(id(witness)) is not witness or witness.thread!=threading.get_ident()):
            raise PermissionError('actual active original Working plan witness required')
        _deadline(witness.deadline)
        entry=self._slot(witness.bundle);working,_=self._seed(entry['seed']);self._check()
        bundle=witness.bundle
        rebase=self._rebases.get(id(witness))
        expected_path=witness.path;inventory=witness.material_inventory
        if rebase is not None:
            if rebase[0] is not witness or self.owner._publication_attempts.get(bundle.id) is not rebase[1]:
                raise PermissionError('original owner publication rebase required')
            expected_path,inventory=rebase[2:]
        published=bundle.path.exists() or bundle.path.is_symlink()
        path=bundle.path if published else bundle.stage_path
        if (path!=expected_path or working['copy'].path!=witness.candidate or
                published and (bundle.stage_path.exists() or bundle.stage_path.is_symlink()) or
                directory_chain(path)[-1]!=json.loads(entry['raw'])['seal']['directory_identity']):
            raise Conflict('original Working plan witness path or publication changed')
        _verify_inventory(path,*inventory,witness.deadline)
        _verify_inventory(witness.candidate,*witness.candidate_inventory,witness.deadline)
        _deadline(witness.deadline)

    @contextmanager
    def _witness(self,bundle):
        """Hash outside writer; hold BOTH pre-hash graphs through owned COMMIT.

        Builder lock is not held across yield. A future actual plan writer must
        still prove its own active DB/request/CAS and current source context.
        Original graphs are borrowed once and retired on every exit, never
        adopted from a copied dataclass, historical fact, JSON or disk path.
        """
        deadline=time.monotonic()+30
        with ExitStack() as cleanup:
            with self._lock:
                _deadline(deadline);entry=self._slot(bundle);working,_=self._seed(entry['seed']);self._check()
                if len(self._witnesses)>=32:raise Conflict('Working plan witness capacity reached')
                path=bundle.path if bundle.path.exists() or bundle.path.is_symlink() else bundle.stage_path
                candidate=working['copy'].path
                material_inventory=cleanup.enter_context(_inventory(path,deadline))
                candidate_inventory=cleanup.enter_context(_inventory(candidate,deadline))
                self.verify(bundle,_operation_deadline=deadline)
                witness=_WorkingPlanWitness(self,bundle,path,candidate,material_inventory,candidate_inventory,
                                            deadline,threading.get_ident())
                self._witnesses[id(witness)]=witness
                try:witness.check()
                except BaseException:
                    self._witnesses.pop(id(witness),None)
                    raise
            try:yield witness
            finally:
                with self._lock:
                    self._rebases.pop(id(witness),None)
                    self._witnesses.pop(id(witness),None)
