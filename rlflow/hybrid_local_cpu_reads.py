"""Cold indexed local CPU historical facts; never runtime/control adoption.

New terminal events archive output/acceptance bytes; older events may not.
Historical proof never reconstructs current liveness or a product Reviewer.
"""
from .hybrid_fixture_runtime_reads import FixtureTaskReader
from .hybrid_local_cpu_profile import KIND, AUTHORIZATION


class LocalCpuTaskReader(FixtureTaskReader):
    _accepted_origin_kind=KIND

    def _point(self,db,read,key,version):
        value=super()._point(db,read,key,version)
        if value['request'].get('fixture_runtime',{}).get('origin',{}).get('kind')==KIND:
            from .hybrid_preparation_sources import historical_sources
            from .hybrid_fixture_runtime_ledger import dependency_lookup
            from .hybrid_budget_ledger import validate_links
            state=historical_sources(self.store,db,value['policy_source'],read)
            from .hybrid_preparation import SECTIONS,EVENTS,validate_record
            from .hybrid_goals import digest
            from .store import Conflict
            for section,field in zip(SECTIONS,('intent_key','result_key')):
                pk=value['preparation'][field];original=read.object(section,pk)
                if original is None:raise Conflict('configured CPU original preparation missing')
                validate_record(section,pk,original)
                proof=self.store._preparation_event(db,pk,max_bytes=min(read.remaining,5*1024**2),
                    _parse=read.parse,_decode=read.decode)
                expected=((EVENTS[SECTIONS.index(section)],'hybrid-core',digest(original),original['accepted_state_version']),
                          [(section,pk,digest(original))])
                if proof!=expected:raise Conflict('configured CPU preparation original event differs')
                state.setdefault(section,{})[pk]=original
                if field=='intent_key':
                    for name,rows in historical_sources(self.store,db,original['sources'],read).items():
                        state.setdefault(name,{}).update(rows)
            validate_links(value,dependency_lookup(self.store,db,read,state))
        return value


    @staticmethod
    def _dto(key,head):
        value=FixtureTaskReader._dto(key,head)
        runtime=head['fixture_runtime'];binding=runtime['origin']['local_cpu']
        from .hybrid_budget import zero
        value.update(kind=KIND,authorization=AUTHORIZATION,
            configured_local_cpu_only=True,fixed_cpu_scope_only=False,
            profile=binding['profile'],approved_spec_sha256=binding['spec_sha256'],
            approved_code_sha256=binding['code_sha256'],
            approved_inputs_sha256=binding['inputs_sha256'],
            recorded_release_attempted=runtime['local_cpu_release_attempted'],
            recorded_terminal_proof_sha256=runtime['terminal_proof_sha256'],
            local_result_status='NOT_DURABLY_ARCHIVED',
            machine_acceptance_status='UNKNOWN',independent_review_status='NOT_PROVEN',
            condition_evidence=False,
            recorded_budget_status=head['status'],
            recorded_reserved_amount=zero() if head['status']=='SETTLED' else dict(head['amount']),
            recorded_unknown_exposure=dict(head['amount']) if head['status']=='UNKNOWN' else zero(),
            cold_recovery_action='READ_ONLY_HISTORY_NO_EXECUTION_REPLAY')
        proof=runtime.get('local_cpu_terminal_proof')
        if proof is not None:
            result=proof['configured_local_result']
            value.update(local_result_status='ARCHIVED' if result is not None else 'RESULT_UNAVAILABLE',
                machine_acceptance_status='UNKNOWN' if result is None else result['machine_acceptance']['status'])
        return value

    def task(self,reservation_id,*,timeline=False):
        value=super().task(reservation_id,timeline=timeline)
        if value is None:return None
        # Never combine different source versions. A concurrent writer causes
        # a read-only retry, never adoption or replay of execution.
        from .hybrid_protocol import ID,validate_schema
        from .hybrid_reads import ReadBudget
        validate_schema(ID,reservation_id)
        with self.snapshot() as (db,meta):
            read=ReadBudget(db,16*1024**2)
            pair=self._head(db,read,reservation_id,meta['as_of_state_version'])
            if pair is None:return None
            head,entry=pair
            if meta['as_of_state_version']!=value['as_of_state_version']:
                from .store import Conflict
                raise Conflict('configured CPU cold snapshot changed; retry read only')
            proof=head['fixture_runtime'].get('local_cpu_terminal_proof')
            value['managed_terminal_proof']=proof
            value['recorded_settled_usage']=None
            if head['fixture_runtime']['phase']=='FIXTURE_SCOPE_STOPPED':
                from .hybrid_budget_ledger import derived_heads,SECTIONS
                from .hybrid_budget import subtract
                project=next(iter(derived_heads(entry)[SECTIONS[3]].values()))
                value['recorded_settled_usage']=subtract(project['consumed'],entry['prior_project']['consumed'])
            return self.output(value,256*1024)


class LocalCpuPublicTaskReader(LocalCpuTaskReader):
    """Authenticated display projection; no private scope/FD/process handles."""

    def task(self,reservation_id,*,timeline=False):
        value=super().task(reservation_id,timeline=timeline)
        if value is None:return None
        proof=value.pop('managed_terminal_proof')
        result=None if proof is None else proof['configured_local_result']
        value['configured_result']=None if result is None else {
            name:result[name] for name in ('outputs','approved_acceptance','machine_acceptance')}
        if result is not None and 'execution' in result:
            value['configured_result']['execution']=result['execution']
        return self.output(value,256*1024)
