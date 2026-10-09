"""Bounded cold original engineering output evidence, never writer authority."""
import json
from contextlib import contextmanager
from .hybrid_candidate_output import SECTIONS,EVENTS,validate_record,validate_links
from .hybrid_budget_ledger import SECTIONS as BUDGET,validate_record as budget_record
from .hybrid_fixture_runtime_ledger import dependency_lookup
from .hybrid_preparation import SECTIONS as PREPARATION,EVENTS as PREPARATION_EVENTS,validate_record as preparation_record
from .hybrid_preparation_sources import historical_sources
from .hybrid_goals import digest
from .hybrid_reads import HybridReader,ReadBudget
from .hybrid_protocol import ID,validate_schema
from .hybrid_registry import Registry
from .store import Store,Conflict,PREPARATION_READ_BYTES


class CandidateOutputReader(HybridReader):
    def __init__(self,store,registry,*,project_id,store_epoch,clock=None):
        if type(store) is not Store or type(registry) is not Registry:
            raise TypeError('cold Store and protected startup Registry required')
        super().__init__(store,project_id=project_id,data_mode='fixture',store_epoch=store_epoch,clock=clock)
        self.registry=registry
        config=json.loads(registry._raw)
        if (config['project_id'],config['data_mode'])!=(project_id,'fixture'):
            raise ValueError('candidate output readonly Registry scope differs')

    @contextmanager
    def snapshot(self):
        with super().snapshot() as (db,meta):
            row=db.execute("SELECT CASE WHEN typeof(version)='integer' THEN version END FROM projection_meta WHERE singleton=1").fetchone()
            if row is None or row[0]!=meta['as_of_state_version']:
                raise Conflict('candidate output readonly projection version differs')
            yield db,meta

    def _domains(self,db,read,version):
        for section in SECTIONS:
            tip,count=self.store._candidate_output_summary(db,section,version)
            projected=db.execute("SELECT COUNT(*) FROM projection WHERE section=? AND object_key!=''",(section,)).fetchone()[0]
            if projected!=count:raise Conflict('candidate output readonly original domain missing')
            if tip is not None:
                value=read.object(section,tip[0])
                if value is None:raise Conflict('candidate output readonly original tip missing')
                validate_record(section,tip[0],value)
                if value['accepted_state_version']!=tip[1]:raise Conflict('candidate output readonly tip version differs')
                self._event(db,read,section,tip[0],value)

    def _event(self,db,read,section,key,value):
        proof=self.store._candidate_output_event(db,key,max_bytes=min(read.remaining,4*1024**2),_parse=read.parse,_decode=read.decode)
        if proof!=((EVENTS[SECTIONS.index(section)],'hybrid-core',digest(value),value['accepted_state_version']),[(section,key,digest(value))]):
            raise Conflict('candidate output readonly original event differs')

    def _point(self,db,read,key,version):
        value=read.object(SECTIONS[1],key)
        if value is None:
            if db.execute('SELECT 1 FROM events WHERE idempotency_key=? AND event_type=?',(key,EVENTS[1])).fetchone():
                raise Conflict('candidate output readonly original fact missing')
            return None
        validate_record(SECTIONS[1],key,value);request=value['request']
        if (any(request[n]!=v for n,v in (('project_id',self.project_id),('data_mode',self.data_mode),('store_epoch',self.store_epoch))) or
                value['accepted_state_version']>version):raise Conflict('candidate output readonly scope/version differs')
        self._event(db,read,SECTIONS[1],key,value)
        pk=request['intent_key'];prior=read.object(SECTIONS[0],pk)
        if prior is None:raise Conflict('candidate output readonly original intent missing')
        validate_record(SECTIONS[0],pk,prior);self._event(db,read,SECTIONS[0],pk,prior)
        tk=request['terminal_key'];terminal=read.object(BUDGET[0],tk)
        if terminal is None:raise Conflict('candidate output readonly original terminal missing')
        budget_record(BUDGET[0],tk,terminal)
        state=historical_sources(self.store,db,terminal['policy_source'],read)
        # The lookup must prove the terminal's entire event, not cache an
        # unchecked projection into state before dependency_lookup sees it.
        lookup=dependency_lookup(self.store,db,read,state)
        if lookup(BUDGET[0],tk)!=terminal:raise Conflict('candidate output readonly terminal differs')
        for section,field in zip(PREPARATION,('intent_key','result_key')):
            original_key=terminal['preparation'][field];original=read.object(section,original_key)
            if original is None:raise Conflict('candidate output readonly preparation missing')
            preparation_record(section,original_key,original)
            proof=self.store._preparation_event(db,original_key,max_bytes=min(read.remaining,5*1024**2),_parse=read.parse,_decode=read.decode)
            if proof!=((PREPARATION_EVENTS[PREPARATION.index(section)],'hybrid-core',digest(original),original['accepted_state_version']),[(section,original_key,digest(original))]):
                raise Conflict('candidate output readonly original preparation event differs')
            state.setdefault(section,{})[original_key]=original
            if field=='intent_key':
                for s,rows in historical_sources(self.store,db,original['sources'],read).items():state.setdefault(s,{}).update(rows)
        for s,rows in historical_sources(self.store,db,value['sources'],read).items():state.setdefault(s,{}).update(rows)
        state.setdefault(SECTIONS[0],{})[pk]=prior
        validate_links(SECTIONS[1],value,lookup)
        return value,terminal

    @staticmethod
    def _dto(key,value,terminal,*,detail=False):
        runtime=terminal['request']['fixture_runtime'];origin=runtime['origin']
        result=runtime['engineering_patch_result']
        dto={'id':key,'task_id':origin['task_id'],'attempt_id':origin['attempt_id'],
            'goal_ref':value['request']['goal_ref'],'contract_revision':value['sources']['contract_revision'],
            'recorded_at':value['recorded_at'],'recorded_at_state_version':value['accepted_state_version'],
            'state':value['state'],'source_coverage':'ORIGINAL_DEPENDENCIES_VERIFIED',
            'current_activation':'HISTORICAL_AUDIT_ONLY','current_execution_status':'UNKNOWN',
            'resource_release_status':'NOT_OBSERVED','actual_cost_status':'UNKNOWN',
            'model_enabled':False,'gpu_enabled':False,'controls_available':False,
            'goal_completed':False,'dispatch_enabled':False,'independent_review_status':'NOT_PERFORMED',
            'target':value['target'],'before_sha256':value['before_sha256'],'after_sha256':value['after_sha256'],
            'base_tree_sha256':value['base_tree']['tree_hash'],'output_tree_sha256':value['output_tree']['tree_hash'],
            'baseline_failed_cases':result['baseline_failed_cases'],'actual_passed_cases':len(value['actual_tests'])}
        if detail:
            dto['evidence']={'actual_tests':value['actual_tests'],'candidate_write_performed':True,
                'candidate_write_fd_closed':True,'historical_runtime_phase':runtime['phase'],
                'historical_pool_release':'FIXTURE_FREE','result_sha256':value['result_hash'],
                'intent_sha256':value['request']['intent_hash'],'source_sha256':result['source_sha256'],
                'program_sha256':origin['program_sha256'],'resource_enforcement':'partial'}
        return dto

    def outputs(self,*,after='',limit=2):
        if type(limit) is not int or not 1<=limit<=5:raise ValueError('bounded candidate output page required')
        if after:validate_schema(ID,after)
        with self.snapshot() as (db,meta):
            read=ReadBudget(db,PREPARATION_READ_BYTES);version=meta['as_of_state_version']
            self._domains(db,read,version)
            rows=db.execute("SELECT CASE WHEN typeof(object_key)='text' AND length(CAST(object_key AS BLOB))<=160 THEN object_key END FROM projection WHERE section=? AND object_key>? AND object_key!='' ORDER BY object_key LIMIT ?",(SECTIONS[1],after,limit+1)).fetchall()
            keys=[]
            for row in rows:
                validate_schema(ID,row[0]);keys.append(row[0])
            items=[]
            for key in keys[:limit]:
                value,terminal=self._point(db,read,key,version);items.append(self._dto(key,value,terminal))
            return self.output({**meta,'items':items,'next_after':keys[limit-1] if len(keys)>limit else None},64*1024)

    def output_detail(self,key):
        validate_schema(ID,key)
        with self.snapshot() as (db,meta):
            read=ReadBudget(db,PREPARATION_READ_BYTES);version=meta['as_of_state_version']
            self._domains(db,read,version);pair=self._point(db,read,key,version)
            if pair is None:return None
            value,terminal=pair
            return self.output({**meta,'candidate':self._dto(key,value,terminal,detail=True)},64*1024)


def install(app,readers,projects,auth):
    import asyncio
    from pathlib import Path
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlError,error_response
    from .hybrid_protocol import ProtocolError
    readers=dict(readers)
    if len(readers)>128:raise ValueError('too many candidate output sources')
    for key,reader in readers.items():
        project=projects.get(key)
        if (type(reader) is not CandidateOutputReader or project is None or project.data_mode!='fixture' or
                reader.project_id!=key or reader.store.root!=Path(project.root).resolve(strict=True)):
            raise ValueError('candidate output readonly startup scope differs')
        with reader.snapshot():pass
    def authorize(request,project_id):
        header=request.headers.get('authorization')
        if header:
            prefix,_,token=header.partition(' ');access=auth.resolve(token,'bearer') if prefix=='Bearer' else None
        else:access=auth.resolve(request.cookies.get('rlflow_session'),'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        if project_id not in readers or not access.principal.allows(project_id):raise ControlError(404,'NOT_FOUND','project not found')
        return readers[project_id]
    async def response(request,project_id,call):
        try:
            reader=authorize(request,project_id);result=await asyncio.to_thread(call,reader)
            authorize(request,project_id)
            if result is None:raise ControlError(404,'NOT_FOUND','candidate output not found')
            await asyncio.to_thread(reader.check_current,result['as_of_state_version']);authorize(request,project_id)
            return JSONResponse(result)
        except ControlError as error:return error_response(error)
        except Conflict:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','candidate output source unavailable',True))
        except (ValueError,ProtocolError):return error_response(ControlError(400,'VALIDATION_ERROR','bounded candidate output query required'))
        except Exception:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','candidate output source unavailable',True))
    @app.get('/api/v1/projects/{project_id}/candidate-outputs')
    async def outputs(request:Request,project_id:str):
        def query(reader):
            if set(request.query_params)-{'after','limit'} or any(len(request.query_params.getlist(k))!=1 for k in request.query_params):raise ValueError('closed candidate output page query required')
            raw=request.query_params.get('limit','2')
            if not raw.isascii() or not raw.isdecimal() or len(raw)>1:raise ValueError('integer page required')
            return reader.outputs(after=request.query_params.get('after',''),limit=int(raw))
        return await response(request,project_id,query)
    @app.get('/api/v1/projects/{project_id}/candidate-outputs/{output_id}')
    async def output_detail(request:Request,project_id:str,output_id:str):
        def query(reader):
            if request.query_params:raise ValueError('closed candidate output detail query required')
            return reader.output_detail(output_id)
        return await response(request,project_id,query)
