"""Bounded indexed Hybrid read views; no writes, leases or execution grants."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math

from .hybrid_goals import (SECTIONS as GOALS, digest, draft_head, head_key,
                          validate_record as goal_record, validate_source)
from .hybrid_authority import (SECTIONS as AUTHORITY, EVENTS, command_key,
                              goal_id, timestamp, _head, validate_record as authority_record)
from .hybrid_protocol import ID, validate_schema
from .observation import ObservationReader
from .store import Conflict, canonical

READ_BYTES=16*1024*1024
OUTPUT_BYTES=2*1024*1024


class ReadBudget:
    """One cumulative byte/node envelope, including source and blob reads."""
    def __init__(self,db,limit=READ_BYTES):
        self.db,self.remaining,self.nodes=db,limit,limit
        self.expanded,self.expanded_nodes=limit,limit
        self.blobs={}

    def charge(self,size,nodes):
        self.expanded-=size;self.expanded_nodes-=nodes
        if self.expanded<0 or self.expanded_nodes<0:raise Conflict('Hybrid expanded source budget exceeded')

    def charge_shape(self,value):
        if isinstance(value,dict):
            self.charge(2+max(0,len(value)-1)+sum(len(canonical(k))+1 for k in value),1+len(value))
        elif isinstance(value,list):self.charge(2+max(0,len(value)-1),1)
        else:self.charge(len(canonical(value)),1)

    def charge_literal(self,value):
        # Literal data must be costed without interpreting marker-like keys.
        stack=[value]
        while stack:
            current=stack.pop();self.charge_shape(current)
            if isinstance(current,dict):stack.extend(current.values())
            elif isinstance(current,list):stack.extend(current)

    def parse(self,raw):
        self.remaining-=len(raw)
        self.nodes-=1+sum(raw.count(c) for c in (b'{',b'[',b',',b':'))
        if self.remaining<0 or self.nodes<0:raise Conflict('Hybrid read budget exceeded')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise Conflict('Hybrid duplicate source key')
                result[key]=value
            return result
        def floating(value):
            number=float(value)
            if not math.isfinite(number):raise Conflict('Hybrid nonfinite source number')
            return number
        def constant(value):raise Conflict('Hybrid nonfinite source number')
        return json.loads(raw,object_pairs_hook=pairs,parse_float=floating,parse_constant=constant)

    def decode(self,value):
        if isinstance(value,dict) and set(value) in ({'$rlflow_blob'},{'$rlflow_blob','literal'}):
            key=value['$rlflow_blob'];literal=value.get('literal',False)
            if not isinstance(key,str) or len(key)!=64 or type(literal) is not bool:
                raise Conflict('Hybrid invalid source descriptor')
            cache_key=(key,literal)
            if cache_key in self.blobs:
                decoded,size,nodes=self.blobs[cache_key]
                self.charge(size,nodes)
                return decoded
            row=self.db.execute('SELECT data FROM blobs WHERE digest=? AND length(data)<=?',(key,self.remaining)).fetchone()
            if row is None or hashlib.sha256(row[0]).hexdigest()!=key:raise Conflict('Hybrid blob unavailable')
            decoded=self.parse(row[0])
            start_size,start_nodes=self.expanded,self.expanded_nodes
            if literal:self.charge_literal(decoded)
            else:decoded=self.decode(decoded)
            self.blobs[cache_key]=(decoded,start_size-self.expanded,start_nodes-self.expanded_nodes)
            return decoded
        self.charge_shape(value)
        if isinstance(value,dict):return {k:self.decode(v) for k,v in value.items()}
        if isinstance(value,list):return [self.decode(v) for v in value]
        return value

    def object(self,section,key):
        row=self.db.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=? THEN value END AS value FROM projection WHERE section=? AND object_key=?',
                            (self.remaining,section,key)).fetchone()
        if row is None:return None
        if row['value'] is None:raise Conflict('Hybrid object exceeds read budget')
        return self.decode(self.parse(row['value'].encode()))


class HybridReader:
    def __init__(self,store,*,project_id,data_mode,store_epoch,clock=None):
        self.store,self.project_id,self.data_mode,self.store_epoch=store,project_id,data_mode,store_epoch
        self.clock=clock or (lambda:datetime.now(timezone.utc))

    @contextmanager
    def snapshot(self):
        with self.store.read_connection() as db:
            try:
                db.execute('BEGIN')
                meta=ObservationReader._meta(db)
                if (meta['project_id'],meta['data_mode'],meta['store_epoch'])!=(self.project_id,self.data_mode,self.store_epoch):
                    raise Conflict('Hybrid source registration changed')
                version=meta['source_version']
                if (type(version) is not int or not 0<=version<=2**63-1
                        or version!=db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]):
                    raise Conflict('Hybrid source version invalid')
                yield db,{'schema_version':'1.1','project_id':self.project_id,'data_mode':self.data_mode,
                          'store_epoch':self.store_epoch,'as_of_state_version':version,'execution_enabled':False}
            except Conflict:raise
            except (ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError):
                raise Conflict('Hybrid source invalid') from None

    @staticmethod
    def output(value,limit=OUTPUT_BYTES):
        if len(canonical(value))>limit:raise Conflict('Hybrid output exceeds read budget')
        return value

    def check_current(self,version):
        """Fresh metadata after the body read; old epoch never becomes current."""
        with self.snapshot() as (db,meta):
            if meta['as_of_state_version']<version:raise Conflict('Hybrid source version regressed')

    def goals(self,*,after='',limit=30):
        if type(limit) is not int or not 1<=limit<=50:raise ValueError('invalid Hybrid page size')
        if after:validate_schema(ID,after)
        with self.snapshot() as (db,meta):
            budget=ReadBudget(db,256*1024)
            rows=list(db.execute('SELECT object_key FROM projection WHERE section=? AND object_key>? AND object_key!=? ORDER BY object_key LIMIT ?',
                                 (GOALS[1],after,'',limit+1)))
            items=[]
            for row in rows[:limit]:
                key=row['object_key'];head=budget.object(GOALS[1],key);goal_record(GOALS[1],key,head)
                if (head['project_id'],head['data_mode'])!=(self.project_id,self.data_mode):raise Conflict('Hybrid head scope mismatch')
                authority=budget.object(AUTHORITY[2],key)
                if authority is not None:
                    authority_record(AUTHORITY[2],key,authority)
                    if (authority['project_id'],authority['data_mode'],authority['goal_id'])!=(self.project_id,self.data_mode,head['goal_id']):
                        raise Conflict('Hybrid authority summary scope mismatch')
                items.append({'goal_ref':key,'contract_revision':head['revision'],'contract_hash':head['contract_hash'],
                              'source_coverage':'HEAD_ONLY','execution_enabled':False,
                              'authority':None if authority is None else {'recorded_state':authority['state'],
                                'authority_revision':authority['authority_revision'],'source_coverage':'HEAD_ONLY'}})
            return self.output({**meta,'items':items,'next_after':items[-1]['goal_ref'] if len(rows)>limit else None},64*1024)

    def _authority(self,db,budget,head,proposal,version):
        if head is None:return None
        hk=head_key(self.project_id,self.data_mode,proposal['goal_id'])
        authority_record(AUTHORITY[2],hk,head)
        if (head['project_id'],head['data_mode'],head['goal_id'])!=(self.project_id,self.data_mode,proposal['goal_id']):
            raise Conflict('Hybrid authority scope mismatch')
        def fact_source(section,key):
            fact=budget.object(section,key)
            if fact is None:raise Conflict('Hybrid authority fact missing')
            authority_record(section,key,fact)
            request=fact['request'];ck=command_key(request)
            receipt=budget.object(AUTHORITY[3],ck)
            if receipt is None:raise Conflict('Hybrid authority receipt missing')
            authority_record(AUTHORITY[3],ck,receipt)
            original_head=_head(request,section,key,fact)
            expected=((EVENTS[request['action']],'hybrid-core',receipt['request_hash'],receipt['accepted_state_version']),
                      sorted([(section,key,digest(fact)),(AUTHORITY[3],ck,digest(receipt)),(AUTHORITY[2],hk,digest(original_head))]))
            source=self.store._authority_event(db,ck,max_bytes=min(budget.remaining,3*1024*1024),_parse=budget.parse,_decode=budget.decode)
            if (source!=expected or receipt['request']!=request or receipt['fact_section']!=section or receipt['fact_key']!=key
                    or receipt['fact_hash']!=digest(fact) or receipt['accepted_state_version']>version
                    or (request['project_id'],request['data_mode'],goal_id(request))!=(self.project_id,self.data_mode,proposal['goal_id'])):
                raise Conflict('Hybrid authority original source mismatch')
            return fact,original_head,receipt['accepted_state_version']
        fact,original_head,fact_version=fact_source(head['fact_section'],head['fact_key'])
        if head!=original_head:raise Conflict('Hybrid authority current head mismatch')
        revoked=fact if head['state']=='REVOKED' else None
        approved=fact
        if revoked is not None:
            approved,_,approved_version=fact_source(AUTHORITY[0],head['approval_key'])
            if (revoked['previous_fact_key']!=head['approval_key'] or revoked['previous_fact_hash']!=digest(approved)
                    or approved['authority_revision']+1!=revoked['authority_revision'] or approved_version>=fact_version):
                raise Conflict('Hybrid revocation predecessor mismatch')
        confirm=approved['request']['confirmation'];now=self.clock()
        return {'recorded_state':head['state'],'authority_revision':head['authority_revision'],'fact_key':head['fact_key'],
                'source_coverage':'ORIGINAL_EVENT_VERIFIED','approved_contract_revision':confirm['expected_revision'],
                'approved_proposal_hash':confirm['proposal_hash'],
                'applies_to_current_contract':(confirm['expected_revision'],confirm['proposal_hash'])==(proposal['contract_version'],digest(proposal)),
                'approved_at':approved['approved_at'],'expires_at':approved['expires_at'],
                'lifetime_status':'EXPIRED' if now>=timestamp(approved['expires_at']) else 'UNEXPIRED',
                'revoked_at':revoked['revoked_at'] if revoked else None,'evaluated_at':now.isoformat().replace('+00:00','Z'),
                'execution_enabled':False}

    def review(self,goal_ref):
        validate_schema(ID,goal_ref)
        with self.snapshot() as (db,meta):
            budget=ReadBudget(db)
            head=budget.object(GOALS[1],goal_ref)
            if head is None:return None
            goal_record(GOALS[1],goal_ref,head)
            if (head['project_id'],head['data_mode'])!=(self.project_id,self.data_mode):raise Conflict('Hybrid goal scope mismatch')
            rk=head['contract_key'];record=budget.object(GOALS[0],rk)
            if record is None:raise Conflict('Hybrid contract missing')
            goal_record(GOALS[0],rk,record);proposal=record['contract']['proposal']
            if head!=draft_head(proposal):raise Conflict('Hybrid contract/head mismatch')
            coverage='PARTIAL_NO_SOURCE_POINTER';accepted=None
            if 'source_command_key' in record:
                ck=record['source_command_key'];receipt=budget.object(GOALS[2],ck)
                if receipt is None:raise Conflict('Hybrid draft receipt missing')
                source=self.store._goal_source(db,ck,max_bytes=budget.remaining,_parse=budget.parse,_decode=budget.decode)
                validate_source(rk,record,ck,receipt,source)
                accepted=receipt['accepted_state_version']
                if accepted>meta['as_of_state_version']:raise Conflict('Hybrid draft source from future')
                coverage='ORIGINAL_EVENT_VERIFIED'
            authority=self._authority(db,budget,budget.object(AUTHORITY[2],goal_ref),proposal,meta['as_of_state_version'])
            return self.output({**meta,'goal_ref':goal_ref,'contract':record['contract'],'changes':record['changes'],
                                'submitted_by':record['submitted_by'],'submitted_at':record['submitted_at'],
                                'previous_hash':record['previous_hash'],'source_coverage':coverage,
                                'submitted_state_version':accepted,'authority':authority})
