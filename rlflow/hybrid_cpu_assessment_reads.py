"""Cold bounded appraisal/raw-evidence reads; never construct a Runtime owner."""
import json
from contextlib import contextmanager
from .hybrid_cpu_assessment import SECTION,EVENT,validate_record,validate_links
from .hybrid_budget_ledger import SECTIONS as BUDGET,EVENT as BUDGET_EVENT,scope,expected_objects,validate_record as budget_record
from .hybrid_budget import account_key
from .hybrid_fixture_runtime_ledger import dependency_lookup
from .hybrid_preparation import (SECTIONS as PREPARATION,EVENTS as PREPARATION_EVENTS,
    source_binding,validate_record as preparation_record)
from .hybrid_preparation_sources import historical_sources,load_sources
from .hybrid_goals import digest
from .hybrid_protocol import ID,validate_schema
from .hybrid_reads import HybridReader,ReadBudget
from .hybrid_registry import Registry
from .hybrid_authority import timestamp
from .store import Store,Conflict,PREPARATION_READ_BYTES


class CpuAssessmentReader(HybridReader):
    def __init__(self,store,registry,*,project_id,store_epoch,clock=None):
        if type(store) is not Store or type(registry) is not Registry:
            raise TypeError('existing readonly Store and protected startup Registry required')
        super().__init__(store,project_id=project_id,data_mode='fixture',store_epoch=store_epoch,clock=clock)
        self.registry=registry
        config=json.loads(registry._raw)
        if (config['project_id'],config['data_mode'])!=(project_id,'fixture'):
            raise ValueError('CPU appraisal readonly protected Registry scope differs')

    @contextmanager
    def snapshot(self):
        with super().snapshot() as (db,meta):
            row=db.execute("SELECT CASE WHEN typeof(version)='integer' THEN version END FROM projection_meta WHERE singleton=1").fetchone()
            if row is None or type(row[0]) is not int or row[0]!=meta['as_of_state_version']:
                raise Conflict('CPU appraisal readonly projection/source version differs')
            yield db,meta

    def _point(self,db,read,key,version):
        value=read.object(SECTION,key)
        if value is None:
            if db.execute('SELECT 1 FROM events WHERE idempotency_key=? AND event_type=?',(key,EVENT)).fetchone():
                raise Conflict('CPU appraisal readonly original fact missing')
            return None
        validate_record(key,value);request=value['request']
        if (any(request[n]!=v for n,v in (('project_id',self.project_id),('data_mode',self.data_mode),('store_epoch',self.store_epoch))) or
                value['accepted_state_version']>version):
            raise Conflict('CPU appraisal readonly scope/version differs')
        prior=None
        if 'prior_assessment_key' in request:
            pk=request['prior_assessment_key'];raw_prior=read.object(SECTION,pk)
            if raw_prior is None or 'prior_assessment_key' in raw_prior.get('request',{}):
                raise Conflict('CPU decision readonly plain original appraisal missing')
            prior=self._point(db,read,pk,version)[0]
        proof=self.store._cpu_assessment_event(db,key,max_bytes=min(read.remaining,256*1024),_parse=read.parse,_decode=read.decode)
        if proof!=((EVENT,'hybrid-core',digest(value),value['accepted_state_version']),[(SECTION,key,digest(value))]):
            raise Conflict('CPU appraisal readonly original event differs')
        terminal_key=request['terminal_key'];terminal=read.object(BUDGET[0],terminal_key)
        if terminal is None:raise Conflict('CPU appraisal readonly original terminal missing')
        budget_record(BUDGET[0],terminal_key,terminal)
        proof=self.store._budget_event(db,terminal_key,max_bytes=min(read.remaining,1024**2),_parse=read.parse,_decode=read.decode)
        if proof!=((BUDGET_EVENT,'hybrid-core',account_key(scope(terminal['request'])),terminal['accepted_state_version']),expected_objects(terminal)):
            raise Conflict('CPU appraisal readonly whole terminal event differs')
        state=historical_sources(self.store,db,terminal['policy_source'],read)
        if prior is not None:state.setdefault(SECTION,{})[request['prior_assessment_key']]=prior
        state.setdefault(BUDGET[0],{})[terminal_key]=terminal
        for section,field in zip(PREPARATION,('intent_key','result_key')):
            pk=terminal['preparation'][field];original=read.object(section,pk)
            if original is None:raise Conflict('CPU appraisal readonly original preparation missing')
            preparation_record(section,pk,original)
            proof=self.store._preparation_event(db,pk,max_bytes=min(read.remaining,5*1024**2),_parse=read.parse,_decode=read.decode)
            if proof!=((PREPARATION_EVENTS[PREPARATION.index(section)],'hybrid-core',digest(original),original['accepted_state_version']),[(section,pk,digest(original))]):
                raise Conflict('CPU appraisal readonly preparation whole event differs')
            state.setdefault(section,{})[pk]=original
            if field=='intent_key':
                for section_name,rows in historical_sources(self.store,db,original['sources'],read).items():
                    state.setdefault(section_name,{}).update(rows)
        for section,rows in historical_sources(self.store,db,value['sources'],read).items():
            state.setdefault(section,{}).update(rows)
        validate_links(value,dependency_lookup(self.store,db,read,state))
        return value,terminal

    def _activation(self,db,read,value):
        sources=value['sources']
        try:
            current=source_binding(load_sources(self.store,db,self.registry,project_id=self.project_id,
                data_mode=self.data_mode,store_epoch=self.store_epoch,goal_ref=sources['goal_ref'],now=self.clock(),_budget=read))
            return all(current[n]==v for n,v in sources.items() if n not in ('source_version','evaluated_at'))
        except Conflict:return False

    @staticmethod
    def _dto(key,value,terminal,*,evidence=False):
        runtime=terminal['request']['fixture_runtime'];origin=runtime['origin']
        dto={'id':key,'experiment_id':origin['task_id'],'attempt_id':origin['attempt_id'],
            'goal_ref':value['request']['goal_ref'],'contract_revision':value['sources']['contract_revision'],
            'recorded_at':value['recorded_at'],'recorded_at_state_version':value['accepted_state_version'],
            'assessment':value['assessment'],'source_coverage':'ORIGINAL_DEPENDENCIES_VERIFIED',
            'model_enabled':False,'gpu_enabled':False,'controls_available':False,
            'current_execution_status':'UNKNOWN','resource_release_status':'NOT_OBSERVED',
            'actual_cost_status':'UNKNOWN','goal_completed':False,'dispatch_enabled':False}
        if evidence:
            result=runtime['cpu_trial_result']
            dto['evidence']=None if result is None else {k:result[k] for k in
                ('raw_samples','inside_counts','estimates','mean_absolute_error','baseline','baseline_absolute_error',
                 'hypothesis_supported','source_sha256','input_sha256','program_sha256','evaluator_sha256',
                 'cpu_ns','worker_wall_ns','cpu_measurement_scope','resource_enforcement','verification')}
        return dto

    def _finish(self,rows,meta):
        # No source or metadata IO after this fresh sample. This is as-of, not
        # an authority promise across network transit or a current process read.
        now=self.clock()
        for dto,value,active in rows:
            sources=value['sources']
            active=active and timestamp(sources['evaluated_at'])<=now<timestamp(sources['expires_at'])
            dto['current_activation']='EXPERIMENT_CURRENT_AS_OF' if active else 'HISTORICAL_ONLY'
            dto['checked_at']=now.isoformat().replace('+00:00','Z')
        return [dto for dto,_,_ in rows]

    def assessments(self,*,after='',limit=2):
        if type(limit) is not int or not 1<=limit<=5:raise ValueError('bounded appraisal page required')
        if after:validate_schema(ID,after)
        with self.snapshot() as (db,meta):
            read=ReadBudget(db,PREPARATION_READ_BYTES)
            _,count=self.store._cpu_assessment_summary(db,meta['as_of_state_version'])
            projected=db.execute("SELECT COUNT(*) FROM projection WHERE section=? AND object_key!=''",(SECTION,)).fetchone()[0]
            if count!=projected:raise Conflict('CPU appraisal readonly domain missing original facts')
            rows=list(db.execute("SELECT CASE WHEN typeof(object_key)='text' AND length(CAST(object_key AS BLOB))<=160 THEN object_key END AS bounded_key FROM projection WHERE section=? AND object_key>? AND object_key!='' ORDER BY object_key LIMIT ?",(SECTION,after,limit+1)))
            keys=[]
            for row in rows:
                key=row['bounded_key']
                if type(key) is not str:raise Conflict('CPU appraisal readonly key exceeds bound')
                validate_schema(ID,key);keys.append(key)
            pending=[]
            for key in keys[:limit]:
                value,terminal=self._point(db,read,key,meta['as_of_state_version'])
                pending.append((self._dto(key,value,terminal),value,self._activation(db,read,value)))
            result={**meta,'items':self._finish(pending,meta),'next_after':keys[limit-1] if len(keys)>limit else None}
            return self.output(result,64*1024)

    def assessment(self,key):
        validate_schema(ID,key)
        with self.snapshot() as (db,meta):
            read=ReadBudget(db,PREPARATION_READ_BYTES);pair=self._point(db,read,key,meta['as_of_state_version'])
            if pair is None:return None
            value,terminal=pair
            row=(self._dto(key,value,terminal,evidence=True),value,self._activation(db,read,value))
            return self.output({**meta,'experiment':self._finish([row],meta)[0]},64*1024)


def install(app,readers,projects,auth):
    import asyncio
    from pathlib import Path
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from .hybrid_control import ControlError,error_response
    from .hybrid_protocol import ProtocolError
    readers=dict(readers)
    if len(readers)>128:raise ValueError('too many CPU appraisal sources')
    for key,reader in readers.items():
        project=projects.get(key)
        if (type(reader) is not CpuAssessmentReader or project is None or project.data_mode!='fixture' or
                reader.project_id!=key or reader.store.root!=Path(project.root).resolve(strict=True)):
            raise ValueError('CPU appraisal readonly startup scope mismatch')
        with reader.snapshot():pass
    def authorize(request,project_id):
        authorization=request.headers.get('authorization')
        if authorization:
            prefix,_,token=authorization.partition(' ');access=auth.resolve(token,'bearer') if prefix=='Bearer' else None
        else:access=auth.resolve(request.cookies.get('rlflow_session'),'session')
        if access is None:raise ControlError(401,'AUTH_REQUIRED','authentication required')
        if project_id not in readers or not access.principal.allows(project_id):raise ControlError(404,'NOT_FOUND','project not found')
        return readers[project_id]
    async def response(request,project_id,call):
        try:
            reader=authorize(request,project_id);result=await asyncio.to_thread(call,reader)
            authorize(request,project_id)
            if result is None:raise ControlError(404,'NOT_FOUND','CPU appraisal not found')
            await asyncio.to_thread(reader.check_current,result['as_of_state_version']);authorize(request,project_id)
            return JSONResponse(result)
        except ControlError as error:return error_response(error)
        except Conflict:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','CPU appraisal source unavailable',True))
        except (ValueError,ProtocolError):return error_response(ControlError(400,'VALIDATION_ERROR','bounded CPU appraisal query required'))
        except Exception:return error_response(ControlError(503,'UNSUPPORTED_CAPABILITY','CPU appraisal source unavailable',True))
    @app.get('/api/v1/projects/{project_id}/cpu-trial-assessments')
    async def assessments(request:Request,project_id:str):
        def query(reader):
            if set(request.query_params)-{'after','limit'} or any(len(request.query_params.getlist(k))!=1 for k in request.query_params):
                raise ValueError('closed appraisal page query required')
            raw=request.query_params.get('limit','2')
            if not raw.isascii() or not raw.isdecimal() or len(raw)>1:raise ValueError('integer appraisal page required')
            return reader.assessments(after=request.query_params.get('after',''),limit=int(raw))
        return await response(request,project_id,query)
    @app.get('/api/v1/projects/{project_id}/cpu-trial-assessments/{assessment_id}')
    async def assessment(request:Request,project_id:str,assessment_id:str):
        def query(reader):
            if request.query_params:raise ValueError('closed appraisal detail query required')
            return reader.assessment(assessment_id)
        return await response(request,project_id,query)
