"""Protected Working plan owner, under construction. NEVER runtime authority.

Original bootstrap/current workspace sources and nonexecuting plan facts use
one owned Controller writer. These facts never permit runtime execution.
Source DTOs are not plan bundles, guards, worker permits or execution leases.
"""
import json
import threading

from .hybrid_installation_service import FixtureInstallationService
from .hybrid_workspace_service import WorkspaceService
from .store import Conflict


class _PlanWriteGuard:
    def __init__(self,owner,context,bundle,attempt,section=None,*,publication=False):
        from .hybrid_working_plan import SECTIONS
        self.owner,self.context,self.db,self.read=owner,context,context.db,context.read
        self.bundle,self.attempt,self.raw=bundle,attempt,attempt['raw']
        self.thread=threading.get_ident();self.dependencies={};self.section=SECTIONS[0] if section is None else section
        self.intent_source=None
        self.publication=publication

    def check(self):self.owner.check_guard(self.db,self)

    def lookup(self,section,key):
        if not key:
            return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        from .hybrid_preparation import SECTIONS as PREPARATION
        from .hybrid_controller import SECTIONS as CONTROLLER
        from .hybrid_budget_ledger import SECTIONS as BUDGET
        from .hybrid_workspace import SECTIONS as WORKSPACE
        from .hybrid_runtime_installation import SECTIONS as INSTALLATION
        from .hybrid_working_plan import SECTIONS as PLANS
        immutable={GOALS[0],GOALS[2],AUTHORITY[0],AUTHORITY[1],AUTHORITY[3],*PREPARATION,
                   CONTROLLER[0],BUDGET[0],WORKSPACE[0],WORKSPACE[2],*INSTALLATION,*PLANS}
        pair=(section,key)
        if section not in immutable:return self.read.object(section,key)
        if pair not in self.dependencies:self.dependencies[pair]=self.read.object(section,key)
        return self.dependencies[pair]


class WorkingPlanService:
    def __init__(self, workspace, installation, material):
        if (type(workspace) is not WorkspaceService or type(installation) is not FixtureInstallationService or
                workspace.store is not installation.store or workspace.data_mode != 'fixture' or
                (workspace.project_id, workspace.store_epoch) != (installation.project_id, installation.store_epoch) or
                workspace.working.namespace != installation.builder._roots['working'] or
                workspace.preparation.builder.source != installation.builder._roots['source'] or
                workspace.preparation.builder.root != installation.builder._roots['snapshots'] or
                not workspace.preparation.adapter.root.is_relative_to(installation.builder._roots['bootstrap'])):
            raise TypeError('fixed actual new fixture Working plan components required')
        installation.builder._slot(material)
        if installation._published is not material:
            raise PermissionError('original published fixture bootstrap required')
        self.workspace, self.installation, self.material = workspace, installation, material
        self.store, self.registry, self.controller = workspace.store, workspace.registry, workspace.controller
        self._lock = threading.RLock(); self._context = None;self._active=None;self._intent_attempts={}
        self._publication_attempts={};self._publication_active=None;self._published={}
        self._publication_pending=None
        self._ready_attempts={}
        # Protected startup only. This is not a free JSON configuration flag.
        if getattr(self.store, '_hybrid_working_plan_service', None) is not None:
            raise Conflict('working plan owner cannot be rebound')
        self.store.bind_hybrid_working_plan(self)
        self._seeds={};self._seed_keys={}
        from .hybrid_working_plan_materials import WorkingPlanMaterialBuilder
        self.builder=WorkingPlanMaterialBuilder(self)

    def observe_sources(self, token, observation):
        """Detached source observation, no durable plan or execution capability.

        Material verification is outside the business writer. Actual source,
        current HEADs, Kernel and original observation are rechecked inside it.
        """
        self.controller._refuse_nested_writer(); self.controller._issued(token)
        with self.workspace._lock:
            slot, _ = self.workspace._issued(observation)
            key = json.loads(slot['witness'].raw)['intent_key']
        witness = self.workspace.preparation.issue_material_witness(key)
        with self.installation._bootstrap_witness(self.material) as bootstrap:
            with self.workspace._plan_context(self, token, observation, witness, bootstrap) as context:
                result = {'sources': json.loads(context.raw), 'state': 'NONEXECUTING_SOURCE_OBSERVATION',
                          'execution_enabled': False, 'release_enabled': False}
        return result

    def start(self, *args, **kwargs):
        raise PermissionError('Working plan/runtime execution gates not implemented')

    def check_guard(self,db,guard):
        from .hybrid_working_plan import SECTIONS,EVENTS,intent_key,result_key,stable_context,expected_objects,event_inputs
        from .hybrid_goals import digest
        from .hybrid_controller import fact_key as controller_key
        from .hybrid_workspace import SECTIONS as WORKSPACE,claim_key
        from .hybrid_preparation import source_binding
        from .store import canonical
        if (type(guard) is not _PlanWriteGuard or self._active is not guard or guard.owner is not self or
                guard.db is not db or guard.thread!=threading.get_ident() or self.store._hybrid_working_plan_service is not self):
            raise PermissionError('actual active original Working plan write guard required')
        context=guard.context;active=self.controller._token_active
        if (self._context is not context or self.workspace._plan_active is not context or context.owner is not self or
                context.db is not db or context.read is not guard.read or guard.read.db is not db or
                active is None or active[0] is not db or active[1] is not context.token or active[2] is not context.read or
                active[3]!=threading.get_ident() or not db.in_transaction):
            raise PermissionError('actual owned Controller/Working plan writer required')
        entry=self.builder._slot(guard.bundle);seed=entry['seed']
        if guard.section not in SECTIONS:raise PermissionError('fixed Working plan phase required')
        attempts=self._intent_attempts if guard.section==SECTIONS[0] else self._ready_attempts
        if (attempts.get(seed.id) is not guard.attempt or guard.raw!=guard.attempt['raw'] or
                seed.token is not context.token or seed.observation is not context.observation or
                context.plan_witness is None or context.plan_witness.bundle is not guard.bundle):
            raise PermissionError('original Working plan request/material binding required')
        value=json.loads(guard.raw);request=value['request'];captured=value['source_context'];now_context=json.loads(context.raw)
        if (value['material_binding']!={'stage_path':str(guard.bundle.stage_path),'published_path':str(guard.bundle.path)} or
                stable_context(captured)!=stable_context(now_context)):
            raise Conflict('actual original Working plan fact/seal/context differs')
        if guard.section==SECTIONS[0]:
            if value['plan']!=json.loads(entry['plan_raw']) or value['expected_seal']!=json.loads(entry['raw'])['seal']:
                raise Conflict('actual original Working INTENT plan/seal differs')
        else:
            from .hybrid_installation_service import _RenameReceipt
            original=self._intent_attempts.get(seed.id);publication=self._publication_attempts.get(seed.id)
            if (original is None or original['bundle'] is not guard.bundle or
                    self._published.get(seed.id) is not guard.bundle or publication is None or
                    publication['bundle'] is not guard.bundle or publication['intent'] is not original or
                    type(publication['receipt']) is not _RenameReceipt or
                    not publication['receipt'].succeeded or context.plan_witness.path!=guard.bundle.path or
                    guard.bundle.stage_path.exists() or guard.bundle.stage_path.is_symlink()):
                raise PermissionError('actual original owner-published Working material required')
            intent=json.loads(original['raw']);ik=intent_key(intent['request'])
            if (request['intent_key']!=ik or request['intent_hash']!=digest(intent) or
                    value['plan_hash']!=digest(intent['plan']) or value['expected_seal_hash']!=digest(intent['expected_seal']) or
                    value['material_binding']!=intent['material_binding'] or
                    stable_context(captured)!=stable_context(intent['source_context'])):
                raise Conflict('READY original INTENT/seal/context differs')
            # Only already-durable immutable proof, only this exact guard/BEGIN.
            # Current heads and this transaction's new READY are never memoized.
            if guard.intent_source is None:
                source=self.store._working_plan_event(db,ik,_parse=guard.read.parse,_decode=guard.read.decode)
                if (guard.lookup(SECTIONS[0],ik)!=intent or source!=
                        ((EVENTS[0],'hybrid-core',guard.bundle.id,intent['accepted_state_version']),
                         expected_objects(SECTIONS[0],ik,intent),event_inputs(intent))):
                    raise Conflict('READY original full INTENT source differs')
                guard.intent_source=(db,guard.read,guard.thread,ik,original['raw'],source)
            elif (guard.intent_source[0] is not db or guard.intent_source[1] is not guard.read or
                    guard.intent_source[2:5]!=(guard.thread,ik,original['raw'])):
                raise PermissionError('original same-transaction INTENT proof required')
        version=self.workspace._metadata(db)
        if guard.publication:
            if (guard.section!=SECTIONS[0] or version!=now_context['sources']['source_version'] or
                    version<value['accepted_state_version']):
                raise Conflict('original Working publication current version changed')
        elif version not in (request['expected_state_version'],value['accepted_state_version']):
            raise Conflict('original Working plan writer CAS changed')
        control=self.controller.check_token_in_transaction(db,context.token,guard.read)
        if captured['controller']!={'fact_key':controller_key(control['request']),'fact_hash':digest(control),
                'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}:
            raise Conflict('Working plan current original controller changed')
        current_sources=source_binding(self.workspace.budget._load(db,request['goal_ref'],guard.read))
        if any(current_sources[n]!=v for n,v in captured['sources'].items() if n not in ('source_version','evaluated_at')):
            raise Conflict('Working plan current Goal consent changed')
        workspace_request={**request,'workspace_id':captured['workspace_head']['workspace_id'],
                           'reservation_id':captured['workspace_head']['reservation_id']}
        current=self.workspace._current(db,workspace_request,guard.read,version)
        _,reservation,_=self.workspace.budget._heads(db,{**workspace_request,'action':'MARK_UNKNOWN'},guard.read,version)
        slot,_=self.workspace._issued(context.observation)
        if (slot['closed'] is not None or self.workspace._unresolved_renewal(slot) or
                current!=captured['workspace_head'] or reservation!=captured['budget_reservation'] or
                guard.read.object(WORKSPACE[2],claim_key(workspace_request))!=captured['workspace_claim']):
            raise Conflict('Working plan current workspace/claim/budget changed')
        if self.installation._bootstrap_point(db,context.bootstrap,guard.read)!=captured['bootstrap']:
            raise Conflict('Working plan original bootstrap changed')
        key=intent_key(request) if guard.section==SECTIONS[0] else result_key(request)
        if version==request['expected_state_version']:
            if guard.read.object(guard.section,key) is not None or self.store._working_plan_event(db,key,
                    _parse=guard.read.parse,_decode=guard.read.decode) is not None:
                raise Conflict('Working plan new original intent already present')
        context.plan_witness.check()
        if canonical(value)!=guard.raw:raise Conflict('Working plan original canonical fact differs')

    def check_live_write(self,db,payload,inputs,guard):
        from .hybrid_working_plan import SECTIONS,intent_key,result_key,event_inputs
        self.check_guard(db,guard)
        if guard.publication:raise PermissionError('physical publication guard cannot append facts')
        value=json.loads(guard.raw)
        key=intent_key(value['request']) if guard.section==SECTIONS[0] else result_key(value['request'])
        put=[[guard.section,key,value]]
        if guard.lookup(guard.section,'') is None:put.append([guard.section,'',{}])
        if payload!={'format':2,'put':put,'delete':[],'details':None} or inputs!=event_inputs(value):
            raise PermissionError('Working plan exact original payload and inputs required')

    def _final_fact(self,context):
        from .hybrid_working_plan import SECTIONS,EVENTS,intent_key,result_key,expected_objects,event_inputs
        from .store import canonical
        guard=self._active
        if guard is None or guard.context is not context:raise PermissionError('actual original Working plan final guard required')
        self.check_guard(context.db,guard);value=json.loads(guard.raw)
        phase=SECTIONS.index(guard.section);key=(intent_key,result_key)[phase](value['request'])
        final_version=json.loads(context.raw)['sources']['source_version'] if guard.publication else value['accepted_state_version']
        if (self.workspace._metadata(context.db)!=final_version or
                context.read.object(guard.section,key)!=value or self.store._working_plan_event(context.db,key,
                    _parse=context.read.parse,_decode=context.read.decode)!=
                ((EVENTS[phase],'hybrid-core',value['request']['plan_id'],value['accepted_state_version']),
                 expected_objects(guard.section,key,value),event_inputs(value))):
            raise Conflict('Working plan final original durable-intent proof differs')
        context.plan_witness.check()

    def persist_intent(self,bundle,token,observation,*,expected_version):
        """Original Working INTENT only, persist before publish; NEVER run."""
        from .hybrid_working_plan import SECTIONS,EVENTS,intent_key,event_inputs,validate_record,stable_context
        from .hybrid_goals import digest
        from .store import canonical
        from .hybrid_protocol import validate_schema
        from .hybrid_workspace import COUNT
        self.controller._refuse_nested_writer();validate_schema(COUNT,expected_version)
        if type(expected_version) is not int:raise Conflict('actual Working plan CAS integer required')
        entry=self.builder._slot(bundle);seed=entry['seed']
        if seed.token is not token or seed.observation is not observation:
            raise PermissionError('original material token and observation required')
        key=json.loads(seed.raw)['context']['preparation']['intent_key']
        preparation=self.workspace.preparation.issue_material_witness(key)
        with self.builder._witness(bundle) as witness,self.installation._bootstrap_witness(self.material) as bootstrap:
            with self.workspace._plan_context(self,token,observation,preparation,bootstrap,plan_witness=witness) as context:
                source=json.loads(context.raw);plan=json.loads(entry['plan_raw'])
                if stable_context(source)!=stable_context(plan['sources']):raise Conflict('original material current sources changed')
                original=self._intent_attempts.get(seed.id)
                if original is None:
                    if source['sources']['source_version']!=expected_version:raise Conflict('Working plan expected writer version changed')
                    request={'project_id':self.workspace.project_id,'data_mode':'fixture','store_epoch':self.workspace.store_epoch,
                        'goal_ref':source['sources']['goal_ref'],'plan_id':bundle.id,'idempotency_key':json.loads(seed.raw)['idempotency_key'],
                        'expected_state_version':expected_version,'action':'prepare_working_plan'}
                    _,mono=self.controller._sample()
                    value={'request':request,'request_hash':digest(request),'accepted_state_version':expected_version+1,
                        'source_context':source,'recorded_at':source['sources']['evaluated_at'],
                        'controller_checked_monotonic_ns':mono,'plan':plan,'expected_seal':json.loads(entry['raw'])['seal'],
                        'material_binding':{'stage_path':str(bundle.stage_path),'published_path':str(bundle.path)},
                        'state':'WORKING_PLAN_INTENT','execution_enabled':False,'release_enabled':False}
                    validate_record(SECTIONS[0],intent_key(request),value)
                    original={'raw':canonical(value),'bundle':bundle};self._intent_attempts[seed.id]=original
                value=json.loads(original['raw'])
                if original['bundle'] is not bundle or value['request']['expected_state_version']!=expected_version:
                    raise Conflict('original Working plan intent request reused')
                guard=_PlanWriteGuard(self,context,bundle,original)
                if self._active is not None:raise Conflict('Working plan writer already active')
                self._active=guard;guard.check();fact_key=intent_key(value['request'])
                duplicate=self.store._existing(context.db,fact_key,EVENTS[0],bundle.id)
                if not duplicate:
                    put=[[SECTIONS[0],fact_key,value]]
                    if guard.lookup(SECTIONS[0],'') is None:put.append([SECTIONS[0],'',{}])
                    payload={'format':2,'put':put,'delete':[],'details':None}
                    self.store._commit(context.db,EVENTS[0],fact_key,payload,expected_version,bundle.id,'hybrid-core',
                        event_inputs(value),_authorization=guard)
                result={'version':value['accepted_state_version'],'intent_key':fact_key,'duplicate':duplicate,
                        'execution_enabled':False,'release_enabled':False}
            return result

    def persist_ready(self,bundle,token,observation,*,expected_version):
        """Second original CAS, known owner publication; NEVER execution."""
        from .hybrid_working_plan import SECTIONS,EVENTS,intent_key,result_key,event_inputs,validate_record,stable_context
        from .hybrid_goals import digest
        from .hybrid_protocol import validate_schema
        from .hybrid_workspace import COUNT
        from .store import canonical
        self.controller._refuse_nested_writer();validate_schema(COUNT,expected_version)
        if type(expected_version) is not int:raise Conflict('actual Working READY CAS integer required')
        entry=self.builder._slot(bundle);seed=entry['seed']
        if seed.token is not token or seed.observation is not observation or self._published.get(seed.id) is not bundle:
            raise PermissionError('actual original owner publication/token/observation required')
        original=self._intent_attempts.get(seed.id)
        if original is None or original['bundle'] is not bundle:raise PermissionError('original Working INTENT required')
        intent=json.loads(original['raw'])
        preparation=self.workspace.preparation.issue_material_witness(json.loads(seed.raw)['context']['preparation']['intent_key'])
        with self.builder._witness(bundle) as witness,self.installation._bootstrap_witness(self.material) as bootstrap:
            with self.workspace._plan_context(self,token,observation,preparation,bootstrap,plan_witness=witness) as context:
                source=json.loads(context.raw)
                if stable_context(source)!=stable_context(intent['source_context']):raise Conflict('READY current sources changed')
                attempt=self._ready_attempts.get(seed.id)
                if attempt is None:
                    if source['sources']['source_version']!=expected_version:raise Conflict('Working READY expected version changed')
                    request={**intent['request'],'action':'publish_working_plan','expected_state_version':expected_version,
                             'intent_key':intent_key(intent['request']),'intent_hash':digest(intent)}
                    _,mono=self.controller._sample()
                    value={'request':request,'request_hash':digest(request),'accepted_state_version':expected_version+1,
                           'source_context':source,'recorded_at':source['sources']['evaluated_at'],
                           'controller_checked_monotonic_ns':mono,'plan_hash':digest(intent['plan']),
                           'expected_seal_hash':digest(intent['expected_seal']),'material_binding':intent['material_binding'],
                           'state':'PLAN_READY_NONEXECUTING','execution_enabled':False,'release_enabled':False}
                    validate_record(SECTIONS[1],result_key(request),value)
                    attempt={'bundle':bundle,'raw':canonical(value)};self._ready_attempts[seed.id]=attempt
                value=json.loads(attempt['raw'])
                if attempt['bundle'] is not bundle or value['request']['expected_state_version']!=expected_version:
                    raise Conflict('original Working READY request reused')
                guard=_PlanWriteGuard(self,context,bundle,attempt,SECTIONS[1])
                if self._active is not None:raise Conflict('Working plan writer already active')
                self._active=guard;guard.check();key=result_key(value['request'])
                duplicate=self.store._existing(context.db,key,EVENTS[1],bundle.id)
                if not duplicate:
                    put=[[SECTIONS[1],key,value]]
                    if guard.lookup(SECTIONS[1],'') is None:put.append([SECTIONS[1],'',{}])
                    self.store._commit(context.db,EVENTS[1],key,{'format':2,'put':put,'delete':[],'details':None},
                        expected_version,bundle.id,'hybrid-core',event_inputs(value),_authorization=guard)
                result={'version':value['accepted_state_version'],'ready_key':key,'duplicate':duplicate,
                        'state':'PLAN_READY_NONEXECUTING','execution_enabled':False,'release_enabled':False}
            return result

    def publish(self,bundle,token,observation,*,expected_version):
        """Original durable INTENT -> native publish -> second-CAS READY."""
        from .hybrid_protocol import validate_schema
        from .hybrid_workspace import COUNT
        validate_schema(COUNT,expected_version)
        if type(expected_version) is not int:raise Conflict('actual Working publication CAS integer required')
        self.builder._slot(bundle)
        if self._published.get(bundle.id) is not bundle:
            self._publish(bundle,token,observation,expected_version=expected_version)
        return self.persist_ready(bundle,token,observation,expected_version=expected_version)

    def _publication_committed(self,context):
        """Fixed owned successful-COMMIT memory ACK, no IO or new authority."""
        pending=self._publication_pending
        if pending is None:return
        attempt,bundle,witness,original_context,guard,receipt=pending
        if (context is not original_context or self._context is not context or
                self.workspace._plan_active is not context or self._active is not guard or
                guard.context is not context or guard.thread!=threading.get_ident() or
                context.plan_witness is not witness or self.builder._witnesses.get(id(witness)) is not witness or
                self._publication_attempts.get(bundle.id) is not attempt or attempt['bundle'] is not bundle or
                attempt['receipt'] is not receipt or not receipt.succeeded):
            raise PermissionError('original pending publication successful-COMMIT ACK required')
        self._published[bundle.id]=bundle # single canonical publication confirmation

    def _publish(self,bundle,token,observation,*,expected_version=None):
        """Private INTENT -> original physical publication; not yet READY."""
        import os
        from .hybrid_installation_service import _rename_no_replace,_RenameReceipt
        from .hybrid_runtime_boundary import _held_chain,directory_chain
        from .hybrid_fixture_materials import _deadline
        self.controller._refuse_nested_writer()
        entry=self.builder._slot(bundle);seed=entry['seed']
        if seed.token is not token or seed.observation is not observation:
            raise PermissionError('original publication token and observation required')
        intent=self._intent_attempts.get(bundle.id)
        if intent is None or intent['bundle'] is not bundle:
            raise PermissionError('actual original persisted Working INTENT required')
        preparation=self.workspace.preparation.issue_material_witness(json.loads(seed.raw)['context']['preparation']['intent_key'])
        with self.builder._witness(bundle) as witness,self.installation._bootstrap_witness(self.material) as bootstrap:
            with self.workspace._plan_context(self,token,observation,preparation,bootstrap,plan_witness=witness) as context:
                if expected_version is not None and json.loads(context.raw)['sources']['source_version']!=expected_version:
                    raise Conflict('original Working publication expected version changed')
                guard=_PlanWriteGuard(self,context,bundle,intent,publication=True);self._active=guard
                guard.check();self._final_fact(context) # actual durable original INTENT, before any rename
                attempt=self._publication_attempts.get(bundle.id)
                if attempt is None:
                    if witness.path!=bundle.stage_path:
                        raise PermissionError('caller move cannot mint Working publication')
                    attempt={'bundle':bundle,'intent':intent,'receipt':None}
                    self._publication_attempts[bundle.id]=attempt
                if attempt['bundle'] is not bundle or attempt['intent'] is not intent:
                    raise Conflict('original Working publication attempt changed')
                if witness.path==bundle.path and (type(attempt['receipt']) is not _RenameReceipt or
                        not attempt['receipt'].succeeded):
                    raise PermissionError('actual owner rename attempt required')
                attempt['witness']=witness;self._publication_active=attempt
                try:
                    with _held_chain(bundle.path.parent) as (fds,chain):
                        if chain!=json.loads(bundle.raw)['seal']['parent_chain']:
                            raise Conflict('original Working publication parent differs')
                        witness.check();_deadline(witness.deadline)
                        if witness.path==bundle.stage_path:
                            receipt=_RenameReceipt(fds[-1],bundle.stage_path.name,bundle.path.name)
                            attempt['receipt']=receipt
                            _rename_no_replace(fds[-1],bundle.stage_path.name,bundle.path.name,_receipt=receipt)
                            self.builder._rebase_publication(witness,attempt)
                        elif witness.path!=bundle.path:
                            raise Conflict('original Working publication path required')
                        witness.check();os.fsync(fds[-1]);_deadline(witness.deadline)
                        if directory_chain(bundle.path.parent)!=chain:
                            raise Conflict('original Working publication parent changed after fsync')
                        witness.check()
                        self._publication_pending=(attempt,bundle,witness,context,guard,attempt['receipt'])
                finally:
                    self._publication_active=None;attempt.pop('witness',None)
                result={'version':json.loads(intent['raw'])['accepted_state_version'],
                        'state':'PUBLISHED_PENDING_READY','execution_enabled':False,'release_enabled':False}
            return result

    def prepare_plan(self,token,observation,idempotency_key):
        """Actual unpublished plan from current Working, not the old snapshot.

        One original seed/material attempt is retained per key, even after an
        uncertain failure. No INTENT/READY or worker is emitted by this method.
        """
        from .hybrid_working_plan_materials import _Seed
        from .hybrid_goals import SECTIONS as GOALS,digest
        from .hybrid_protocol import ID,validate_schema
        from .store import canonical
        import uuid
        validate_schema(ID,idempotency_key)
        self.controller._refuse_nested_writer();self.controller._issued(token)
        with self._lock:
            original=self._seed_keys.get(idempotency_key)
            if original is not None:
                if original.token is not token or original.observation is not observation:
                    raise Conflict('original Working plan request key reused')
        if original is not None:return self.builder.build(original)
        with self.workspace._lock:
            slot,_=self.workspace._issued(observation);key=json.loads(slot['witness'].raw)['intent_key']
        witness=self.workspace.preparation.issue_material_witness(key)
        with self.installation._bootstrap_witness(self.material) as bootstrap:
            with self.workspace._plan_context(self,token,observation,witness,bootstrap) as context:
                sources=json.loads(context.raw);record=context.read.object(GOALS[0],sources['sources']['contract_key'])
                if record is None or digest(record)!=sources['sources']['record_hash']:
                    raise Conflict('original Working plan proposal record differs')
                # Existing preparation owns the original role/profile/schema;
                # its snapshot path is not rewritten or adopted as Working.
                plan=json.loads(witness.materials[1].raw)
                value={'idempotency_key':idempotency_key,'context':sources,
                       'proposal':record['contract']['proposal'],'preparation_plan':plan}
            with self._lock:
                if len(self._seeds)>=128:raise Conflict('Working plan seed capacity reached')
                if idempotency_key in self._seed_keys:raise Conflict('another original Working plan request won')
                seed=_Seed('working_plan_'+uuid.uuid4().hex,canonical(value),token,observation,witness.materials)
                self._seeds[seed.id]=seed;self._seed_keys[idempotency_key]=seed
        # All current-candidate hashing and policy/material writes are OUTSIDE
        # the Store writer and Controller/Workspace/Working context locks.
        return self.builder.build(seed)
