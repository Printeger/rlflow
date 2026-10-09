"""Cold original result -> real contract conditions -> honest delivery gaps.

Machine context is NOT ConditionEvidence. No caller-supplied PASS/session ID,
new model session, write, owner reconstruction or Goal transition is accepted.
"""
from pathlib import Path

from .hybrid_cpu_assessment_reads import CpuAssessmentReader
from .hybrid_candidate_output_reads import CandidateOutputReader
from .hybrid_goals import SECTIONS as GOALS,digest,draft_head,validate_record,validate_source
from .hybrid_authority import SECTIONS as AUTHORITY,EVENTS,command_key,timestamp
from .hybrid_preparation_sources import historical_sources,load_sources
from .hybrid_preparation import source_binding
from .hybrid_protocol import ID,ProtocolError,validate_schema
from .hybrid_reads import HybridReader,ReadBudget
from .store import Conflict,PREPARATION_READ_BYTES,canonical


class DeliveryEvidenceReader(HybridReader):
    MAX_HEAD_SUFFIX=256

    def __init__(self,source):
        if type(source) not in (CpuAssessmentReader,CandidateOutputReader):
            raise TypeError('exact cold original result reader required')
        super().__init__(source.store,project_id=source.project_id,data_mode='fixture',
            store_epoch=source.store_epoch,clock=source.clock)
        self.source=source
        self.kind='CPU_TRIAL' if type(source) is CpuAssessmentReader else 'ENGINEERING'
        self._binding=(source,source.store,source.registry,source.project_id,source.store_epoch,source.registry._raw)
        self._original()

    def _original(self):
        source,store,registry,project,epoch,raw=self._binding
        if (self.source is not source or source.store is not store or source.registry is not registry or
                self.store is not store or (source.project_id,source.data_mode,source.store_epoch)!=
                (project,'fixture',epoch) or (self.project_id,self.data_mode,self.store_epoch)!=
                (project,'fixture',epoch) or registry._raw!=raw or
                self.kind!=('CPU_TRIAL' if type(source) is CpuAssessmentReader else 'ENGINEERING')):
            raise Conflict('original delivery evidence source binding changed')

    def _contract(self,db,read,meta,goal):
        head=read.object(GOALS[1],goal)
        if head is None:raise Conflict('original result current Goal head missing')
        validate_record(GOALS[1],goal,head)
        if (head['project_id'],head['data_mode'])!=(self.project_id,self.data_mode):
            raise Conflict('delivery current Goal scope differs')
        key=head['contract_key'];record=read.object(GOALS[0],key)
        if record is None:raise Conflict('delivery current contract missing')
        validate_record(GOALS[0],key,record);proposal=record['contract']['proposal']
        if head!=draft_head(proposal) or 'source_command_key' not in record:
            raise Conflict('delivery requires original current contract source')
        command=record['source_command_key'];receipt=read.object(GOALS[2],command)
        if receipt is None:raise Conflict('delivery current contract receipt missing')
        proof=self.store._goal_source(db,command,max_bytes=read.remaining,_parse=read.parse,_decode=read.decode)
        validate_source(key,record,command,receipt,proof)
        if receipt['accepted_state_version']>meta['as_of_state_version']:
            raise Conflict('delivery current contract from future')
        self._latest_head(db,read,GOALS[1],goal,receipt['accepted_state_version'],meta['as_of_state_version'],command)
        authority_head=read.object(AUTHORITY[2],goal)
        authority=self._authority(db,read,authority_head,proposal,meta['as_of_state_version'])
        authority_version=0
        authority_command=None
        if authority_head is not None:
            fact=read.object(authority_head['fact_section'],authority_head['fact_key'])
            authority_command=command_key(fact['request'])
            authority_version=read.object(AUTHORITY[3],authority_command)['accepted_state_version']
        self._latest_head(db,read,AUTHORITY[2],goal,authority_version,meta['as_of_state_version'],authority_command)
        # The approval witness has already passed its original full source
        # proof. Any protected Registry drift is explicitly historical, not
        # inferred from a generic source/budget exception downstream.
        approved=None if authority_head is None else read.object(AUTHORITY[0],authority_head['approval_key'])
        registry_matches=approved is not None and canonical(approved['registry_witness'])==self.source.registry._raw
        return proposal,authority,registry_matches

    def _current_sources(self,db,read,goal,registry_matches):
        if not registry_matches:return None
        try:
            return source_binding(load_sources(self.store,db,self.source.registry,project_id=self.project_id,
                data_mode=self.data_mode,store_epoch=self.store_epoch,goal_ref=goal,now=self.clock(),_budget=read))
        except Conflict as exc:
            if str(exc) not in ('preparation current consent unavailable',
                    'preparation approval configuration or lifetime changed'):raise
            return None

    def _latest_head(self,db,read,section,goal,accepted,version,command):
        """Prove absence of later original head writes, never trust projection.

        A bounded PK suffix (including unrelated events) avoids unbounded replay
        or a new persistence index. Beyond the window the whole read fails
        closed; old genuine heads cannot be relabelled current. Source bodies
        and blob expansion share the original cumulative read envelope.
        """
        if command is not None:
            base=db.execute('SELECT seq,previous_state_version,new_state_version FROM events WHERE idempotency_key=?',(command,)).fetchone()
            if base is None or tuple(base)!=(accepted,accepted-1,accepted):
                raise Conflict('delivery latest head original baseline differs')
            read.charge_literal(dict(base))
        rows=db.execute('SELECT seq,previous_state_version,new_state_version,CASE WHEN length(CAST(event_type AS BLOB))<=128 THEN event_type END AS event_type,CASE WHEN length(CAST(idempotency_key AS BLOB))<=160 THEN idempotency_key END AS idempotency_key FROM events WHERE seq>? AND seq<=? ORDER BY seq LIMIT ?',
            (accepted,version,self.MAX_HEAD_SUFFIX+1)).fetchall()
        if len(rows)>self.MAX_HEAD_SUFFIX:raise Conflict('delivery latest head proof window exceeded')
        previous=accepted
        for row in rows:
            read.charge_literal(dict(row))
            if (row['event_type'] is None or row['idempotency_key'] is None or row['seq']!=previous+1 or row['previous_state_version']!=previous or row['new_state_version']!=row['seq']):
                raise Conflict('delivery latest head proof suffix is incomplete')
            previous=row['seq']
            if section==GOALS[1] and row['event_type']=='HYBRID_GOAL_DRAFTED':
                proof=self.store._goal_source(db,row['idempotency_key'],max_bytes=read.remaining,
                    _parse=read.parse,_decode=read.decode)
            elif section==AUTHORITY[2] and row['event_type'] in EVENTS.values():
                proof=self.store._authority_event(db,row['idempotency_key'],max_bytes=min(read.remaining,3*1024**2),
                    _parse=read.parse,_decode=read.decode)
            else:continue
            if proof is None or proof[0][0]!=row['event_type'] or proof[0][1]!='hybrid-core' or proof[0][3]!=row['seq']:
                raise Conflict('delivery later original head source differs')
            if any(s==section and k==goal for s,k,h in proof[1]):
                raise Conflict('delivery projected head is not latest original head')
        if previous!=version:raise Conflict('delivery latest head proof suffix is incomplete')

    def inspect(self,key):
        validate_schema(ID,key)
        try:return self._inspect(key)
        except Conflict:raise
        except (ProtocolError,ValueError,TypeError,KeyError) as exc:
            raise Conflict('delivery original source schema unavailable') from exc

    def _inspect(self,key):
        self._original()
        prefix='cpu_assessment_' if self.kind=='CPU_TRIAL' else 'candidate_output_result_'
        if not key.startswith(prefix):return None
        source=self.source
        # ALL result, original contract and current contract proofs share one
        # original readonly transaction and cumulative read envelope.
        with source.snapshot() as (db,meta):
            read=ReadBudget(db,PREPARATION_READ_BYTES);version=meta['as_of_state_version']
            if self.kind=='ENGINEERING':source._domains(db,read,version)
            pair=source._point(db,read,key,version)
            if pair is None:return None
            value,terminal=pair[:2];binding=value['sources']
            history=historical_sources(self.store,db,binding,read)
            original=history[GOALS[0]][binding['contract_key']]['contract']['proposal']
            proposal,authority,registry_matches=self._contract(db,read,meta,value['request']['goal_ref'])
            if self.kind=='CPU_TRIAL':
                machine=value.get('machine_verification')
                result=terminal['request']['fixture_runtime']['cpu_trial_result']
                context={'profile':'FIXED_CPU_PI_TRIAL_V1','machine_status':
                    'NOT_RECORDED' if machine is None else machine['status'],
                    'candidate_binding_kind':'FIXED_COMMAND_SHA256',
                    'candidate_sha256':terminal['request']['fixture_runtime']['origin']['cpu_trial']['command_sha256'],
                    'raw_item_count':0 if result is None else sum(len(r['points']) for r in result['raw_samples'])}
            else:
                machine=source._acceptance(db,read,key,value,version,pair[2])
                context={'profile':'FIXED_ENGINEERING_PATCH_UNIT','machine_status':
                    'NOT_RECORDED' if machine is None else machine['status'],
                    'candidate_binding_kind':'OUTPUT_TREE_SHA256','candidate_sha256':value['output_tree']['tree_hash'],
                    'raw_item_count':len(value['actual_tests'])}
            context.update(source_id=key,source_kind=self.kind,source_sha256=digest(value),
                result_sha256=value['result_hash'],configuration_sha256=binding['config_hash'],
                original_proposal_sha256=binding['proposal_hash'],original_contract_revision=original['contract_version'],
                recorded_state_version=value['accepted_state_version'],
                verifier_sha256=None if machine is None else machine['verifier_sha256'],
                machine_case_count=0 if machine is None or machine.get('derived') is None else
                    machine['derived'].get('passed_cases',0),
                original_model_budget={n:original['budget'][n] for n in
                    ('model_sessions','model_input_tokens','model_output_tokens')},
                evidence_role='UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE')
            same_contract=digest(proposal)==binding['proposal_hash']
            current=self._current_sources(db,read,value['request']['goal_ref'],registry_matches)
            active=current is not None and same_contract and all(current[n]==v for n,v in binding.items() if n not in ('source_version','evaluated_at'))
            # No source IO beyond this final time sample. A heartbeat cannot
            # renew the original consent or turn stale context into evidence.
            now=self.clock();active=active and timestamp(binding['evaluated_at'])<=now<timestamp(binding['expires_at'])
            consent=current is not None and timestamp(current['evaluated_at'])<=now<timestamp(current['expires_at']) and authority is not None and authority['recorded_state']=='LEASE_VALIDATION_PENDING' and authority['applies_to_current_contract'] and timestamp(authority['approved_at'])<=now<timestamp(authority['expires_at'])
            missing=['MISSING_CONDITION_EVIDENCE','MISSING_INDEPENDENT_REVIEW']
            if not same_contract:missing.append('CURRENT_CONTRACT_DIFFERS')
            if not consent:missing.append('CURRENT_CONSENT_UNAVAILABLE')
            if not active:missing.append('RESULT_HISTORICAL_ONLY')
            conditions=[{'id':c['id'],'description':c['description'],'required':c['required'],
                'verification':c['verification'],'verification_sha256':digest(c['verification']),
                'status':'UNASSESSED','condition_evidence_refs':[],
                'machine_context_refs':[key] if same_contract else [],
                'missing':list(missing)} for c in proposal['global_conditions']]
            self._original()
            return self.output({**meta,'goal_ref':value['request']['goal_ref'],
                'contract_revision':proposal['contract_version'],'proposal_sha256':digest(proposal),
                'source_coverage':'ORIGINAL_RESULT_AND_CURRENT_CONTRACT_VERIFIED',
                'result_activation':'CURRENT_SOURCE_AS_OF' if active else 'HISTORICAL_ONLY',
                'consent_status':'CURRENT_AS_OF' if consent else 'UNAVAILABLE_AS_OF',
                'checked_at':now.isoformat().replace('+00:00','Z'),'machine_context':context,
                'conditions':conditions,'required_count':sum(c['required'] for c in conditions),
                'required_satisfied_count':0,'finalization_status':'BLOCKED_MISSING_EVIDENCE',
                'blockers':missing,'independent_review_status':'NOT_PERFORMED',
                'goal_completed':False,'dispatch_enabled':False,'model_call_enabled':False,
                'condition_evidence_write_enabled':False})


def install(app,readers,projects,auth):
    """Explicit opt-in cold read only; no acceptance of externally claimed PASS."""
    import asyncio
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlError,error_response
    from .hybrid_protocol import ProtocolError
    captured=dict(readers)
    if len(captured)>128:raise ValueError('bounded delivery sources required')
    for (project_id,kind),reader in captured.items():
        project=projects.get(project_id)
        if (type(reader) is not DeliveryEvidenceReader or project is None or project.data_mode!='fixture' or
                (reader.project_id,reader.kind)!=(project_id,kind) or reader.store.root!=Path(project.root).resolve(strict=True)):
            raise ValueError('original delivery startup source differs')
        reader._original()
        with reader.source.snapshot():pass
    def authorize(request,project,kind):
        header=request.headers.get('authorization')
        if header:
            prefix,_,token=header.partition(' ');access=auth.resolve(token,'bearer') if prefix=='Bearer' else None
        else:access=auth.resolve(request.cookies.get('rlflow_session'),'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        reader=captured.get((project,kind))
        if reader is None or not access.principal.allows(project):raise ControlError(404,'NOT_FOUND','delivery source not found')
        return reader
    @app.get('/api/v1/projects/{project_id}/delivery-evidence/{kind}/{source_id}')
    async def inspect(request:Request,project_id:str,kind:str,source_id:str):
        try:
            if request.query_params:raise ValueError('closed delivery evidence query required')
            reader=authorize(request,project_id,kind)
            result=await asyncio.to_thread(reader.inspect,source_id)
            authorize(request,project_id,kind)
            if result is None:raise ControlError(404,'NOT_FOUND','original result not found')
            await asyncio.to_thread(reader.check_current,result['as_of_state_version'])
            authorize(request,project_id,kind)
            return JSONResponse(result)
        except ControlError as exc:return error_response(exc)
        except Conflict:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','delivery original source unavailable',True))
        except (ValueError,ProtocolError):return error_response(ControlError(400,'VALIDATION_ERROR','closed original delivery query required'))
        except Exception:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','delivery original source unavailable',True))
