"""Human control of original approved finite engineering Unit, never cold adoption."""
from .hybrid_cpu_unit_control import _OriginalUnitControl, _install_units
from .hybrid_fixture_runtime_reads import FixtureTaskReader
from .hybrid_fixture_runtime_ledger import ENGINEERING_CONTROL_BODY
from .hybrid_engineering_execution_unit import EngineeringExecutionUnit
from .hybrid_engineering_patch import KIND, AUTHORIZATION
from . import hybrid_engineering_unit_stop as stop_domain


class EngineeringUnitTaskReader(FixtureTaskReader):
    _accepted_origin_kind = KIND

    @staticmethod
    def _dto(key,head):
        return {**FixtureTaskReader._dto(key,head),'kind':KIND,'authorization':AUTHORIZATION}


class EngineeringUnitControlService(_OriginalUnitControl):
    _unit_type = EngineeringExecutionUnit
    _reader_type = EngineeringUnitTaskReader
    _stop_domain = stop_domain
    _start_body = ENGINEERING_CONTROL_BODY
    _start_action = 'START_FIXED_ENGINEERING'
    _stop_action = 'CANCEL_FIXED_ENGINEERING'
    _profile = 'FIXED_ENGINEERING_PATCH_UNIT'
    _store_slot = '_hybrid_engineering_unit_control_service'
    _store_bind = 'bind_hybrid_engineering_unit_control'
    _store_proof = '_engineering_unit_stop_event'

    def _after_stop_cleanup(self):
        # Only original already-entered write readback; never new acceptance,
        # Controller/session renewal, second pwrite or worker redispatch.
        row=self.unit.output._rows.get(id(self.unit.lease))
        if row is not None and row['material'].write_entered:
            self.unit.output.reconcile(self.unit.lease)


def install(app,services,projects,auth,*,origin,max_jobs):
    return _install_units(app,services,projects,auth,origin=origin,max_jobs=max_jobs,
        service_type=EngineeringUnitControlService,path='engineering-unit',
        start_action='START_FIXED_ENGINEERING',stop_action='CANCEL_FIXED_ENGINEERING',
        state_prefix='engineering_unit')
