"""Private composition of already-approved original fixed Unit controls.

No scheduler, grant/lease/Controller construction, cold adoption or OS sampling.
The app reads original evidence and cached telemetry; POSTs use existing scoped
control services. One original HostPool, 1-3 distinct project owners, same Auth.
"""
from .hybrid_cpu_unit_control import CpuUnitControlService
from .hybrid_engineering_unit_control import EngineeringUnitControlService
from .hybrid_host_execution import HostExecutionService
from .hybrid_resource_telemetry import FixedUnitTelemetry
from .web_auth import AuthStore
from .web_api import Project,create_app


def create_finite_host_app(host,controls,auth,*,origin,observers=(),max_streams=8,max_control_jobs=4):
    if type(host) is not HostExecutionService or type(auth) is not AuthStore:
        raise TypeError('actual original finite Host and same AuthStore required')
    host._pure_identity()  # Reject fork/copy before inherited locks or IO.
    if type(max_streams) is not int or not 1<=max_streams<=16:
        raise ValueError('invalid stream limit')
    if type(max_control_jobs) is not int or not 1<=max_control_jobs<=8:
        raise ValueError('invalid control limit')
    if type(controls) not in (tuple,list):
        raise ValueError('finite immutable 1-3 original controls required')
    controls=tuple(controls[:4])
    if not 1<=len(controls)<=3:
        raise ValueError('finite immutable 1-3 original controls required')
    if type(observers) not in (tuple,list):
        raise ValueError('finite original observer tuple required')
    observers=tuple(observers[:4])
    if len(observers)>3:
        raise ValueError('finite original observer tuple required')
    projects=[];cpu={};engineering={};units={};telemetry={};roots=set();identities=set()
    for service in controls:
        if type(service) not in (CpuUnitControlService,EngineeringUnitControlService):
            raise TypeError('exact original fixed Unit control required')
        service._pure()
        runtime=service.runtime;workspace=runtime.workspace
        if (service.host is not host or runtime.pool is not host.pool or
                service.auth is not auth or runtime.store._hybrid_auth_owner is not auth or
                service.origin!=origin or service.project_id in units or
                service.store.root in roots or id(service.unit) in identities or
                (service.project_id,service.store_epoch)!=(workspace.project_id,workspace.store_epoch) or
                service.store is not runtime.store or service.reader.store is not service.store):
            raise ValueError('original shared Host/Auth/project binding differs')
        if (type(service.reader) is not service._reader_type or
                (service.reader.project_id,service.reader.data_mode,service.reader.store_epoch)!=
                (service.project_id,'fixture',service.store_epoch)):
            raise ValueError('original control reader binding differs')
        with service.reader.snapshot(): pass
        units[service.project_id]=service.unit
        roots.add(service.store.root);identities.add(id(service.unit))
        projects.append(Project(service.project_id,str(service.store.root),'fixture'))
        target=cpu if type(service) is CpuUnitControlService else engineering
        target[service.project_id]=service
    for observer in observers:
        if type(observer) is not FixedUnitTelemetry:
            raise TypeError('actual original fixed observer required')
        observer._original()
        if (observer.host is not host or units.get(observer.project_id) is not observer.unit or
                observer.project_id in telemetry):
            raise ValueError('original shared app observer binding differs')
        telemetry[observer.project_id]=observer
    # Entire finite capture/preflight above precedes app/control-pool assembly.
    # These readers never construct owners from history or infer new authority.
    from .hybrid_cpu_assessment_reads import CpuAssessmentReader
    from .hybrid_candidate_output_reads import CandidateOutputReader
    cpu_readers={key:CpuAssessmentReader(s.store,s.runtime.plans.registry,
        project_id=key,store_epoch=s.store_epoch) for key,s in cpu.items()}
    engineering_readers={key:CandidateOutputReader(s.store,s.runtime.plans.registry,
        project_id=key,store_epoch=s.store_epoch) for key,s in engineering.items()}
    for reader in (*cpu_readers.values(),*engineering_readers.values()):
        with reader.snapshot(): pass
    from .hybrid_delivery_evidence import DeliveryEvidenceReader
    delivery={(key,'CPU_TRIAL'):DeliveryEvidenceReader(reader) for key,reader in cpu_readers.items()}
    delivery.update({(key,'ENGINEERING'):DeliveryEvidenceReader(reader) for key,reader in engineering_readers.items()})
    from .hybrid_finite_host_stop import FiniteHostStop,install
    coordinator=FiniteHostStop(host,controls,auth,origin=origin)
    try:
        app=create_app(projects,auth,origin=origin,max_streams=max_streams,max_control_jobs=max_control_jobs,
            cpu_unit_services=cpu,engineering_unit_services=engineering,
            cpu_assessment_readers=cpu_readers,candidate_output_readers=engineering_readers,
            fixed_unit_telemetry=telemetry,delivery_evidence_readers=delivery)
        install(app,coordinator)
        return app
    except BaseException:
        coordinator.close()
        raise
