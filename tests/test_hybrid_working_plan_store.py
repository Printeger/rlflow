"""Private Store denial and isolated original-source-helper diagnostics.

Synthetic event rows are inserted ONLY in a disposable separate database to
exercise its reader. They are not service writes, replay acceptance or runtime.
Actual durable plan INTENT/READY still require a future live owner guard.
"""
from copy import deepcopy
import json

import pytest

from rlflow.hybrid_working_plan import SECTIONS,EVENTS,intent_key,event_inputs,expected_objects
from rlflow.hybrid_goals import digest
from rlflow.store import Store,Conflict,canonical,sha
from rlflow.snapshot_maintenance import maintain
from tests.test_hybrid_working_plan import facts
from tests.test_hybrid_working_plan_service import plans
from tests.test_execution_adapter import setup as native_setup


@pytest.mark.parametrize('operation',['event','objects','whole_state','direct_commit','dto_guard'])
def test_store_generic_plan_writes_and_dto_guard_denied_before_idempotency(facts,operation):
    owner,bundle,state,intent,_=facts;key=intent_key(intent['request']);before=owner.store.audit()
    payload={'format':2,'put':[[SECTIONS[0],key,intent],[SECTIONS[0],'',{}]],'delete':[],'details':None}
    def mutate(after):after.setdefault(SECTIONS[0],{})[key]=intent
    with pytest.raises(PermissionError):
        if operation=='whole_state':owner.store.transact(EVENTS[0],key,mutate,object_id=bundle.id)
        elif operation in ('event','objects'):
            owner.store.transact_objects(EVENTS[0] if operation=='event' else 'GENERIC_WRITE',key,[(SECTIONS[0],key)],
                mutate,expected=state['version'],object_id=bundle.id)
        else:
            with owner.store.lock(),owner.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                owner.store._commit(db,EVENTS[0],key,payload,state['version'],bundle.id,'hybrid-core',event_inputs(intent),
                    _authorization=intent if operation=='dto_guard' else None)
    assert owner.store.audit()==before and not owner.store.objects(SECTIONS[0])


def test_empty_plan_domain_actual_audit_replay_manual_periodic_and_recovery(plans):
    owner,_,_,_,_,_,_=plans;state=owner.store.audit()
    assert owner.store.replay()==state
    with owner.store.read_connection() as db:assert owner.store._working_plan_summary(db,state['version'])==(None,0)
    owner.store.snapshot();assert owner.store.recover()==state
    with owner.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(state['version'],))
    assert maintain(owner.store,seconds=30) and owner.store.recover()==state
    attached=Store.attach_existing(owner.store.root,project_id=owner.workspace.project_id,data_mode='fixture')
    assert attached._hybrid_working_plan_service is None
    assert attached.audit()==state


@pytest.mark.parametrize('target',['runtime','database','writer_lock'])
def test_new_fixture_store_private_permissions_not_host_umask_and_late_damage_denies(plans,target):
    owner,token,observation,_,_,_,_=plans
    import stat
    paths={'runtime':owner.store.db.parent,'database':owner.store.db,
           'writer_lock':owner.store.root/'runtime/writer.lock'}
    for name,path in paths.items():assert stat.S_IMODE(path.stat().st_mode)==(0o700 if name=='runtime' else 0o600)
    path=paths[target];original=path.stat().st_mode&0o777
    try:
        path.chmod(0o775 if target=='runtime' else 0o664)
        with pytest.raises(Conflict):owner.observe_sources(token,observation)
    finally:path.chmod(original)


def test_new_runtime_rebind_before_chmod_denies_without_touching_foreign_files(tmp_path,monkeypatch):
    from rlflow import hybrid_fixture_materials as materials
    import stat
    original=materials.Store;foreign=[]
    def rebound(root):
        store=original(root);runtime=store.db.parent
        runtime.rename(runtime.with_name('original-runtime'))
        runtime.mkdir(mode=0o700)
        for name in ('research.db','writer.lock'):
            path=runtime/name;path.write_bytes(b'foreign existing file');path.chmod(0o644);foreign.append(path)
        return store
    monkeypatch.setattr(materials,'Store',rebound)
    with pytest.raises(Conflict,match='runtime changed during Store creation'):
        materials.FixtureMaterialBuilder(tmp_path,project_id='fixture_new_runtime_rebind')
    assert foreign and all(path.read_bytes()==b'foreign existing file' and stat.S_IMODE(path.stat().st_mode)==0o644 for path in foreign)


@pytest.mark.parametrize('target',['research.db','writer.lock'])
def test_new_store_files_are_pinned_before_enable_no_recreation(tmp_path,monkeypatch,target):
    from rlflow import hybrid_fixture_materials as materials
    original=materials.enable;seen=[]
    def missing(store,**kwargs):
        path=store.db.parent/target
        assert store._existing_identity is not None and store._existing_lock_identity is not None
        path.rename(path.with_name('retained-'+target));seen.append(path)
        return original(store,**kwargs)
    monkeypatch.setattr(materials,'enable',missing)
    with pytest.raises(OSError):materials.FixtureMaterialBuilder(tmp_path,project_id='fixture_no_recreate_before_enable')
    assert seen and not seen[0].exists() and seen[0].with_name('retained-'+target).exists()


@pytest.mark.parametrize('damage',['none','input_fact_hash','noncanonical_inputs','object_id','producer','previous_version',
    'new_version','object_version','marker','duplicate','extra','rehashed_material_path','payload_hash','body_noncanonical','bound'])
def test_indexed_original_helper_complete_metadata_and_wholefact_input_anchor(facts,tmp_path,damage):
    _,_,_,original,_=facts;value=deepcopy(original);key=intent_key(value['request']);version=value['accepted_state_version']
    inputs=event_inputs(value)
    if damage=='rehashed_material_path':
        from pathlib import Path
        path=Path(value['material_binding']['published_path']);parent=path.parent.with_name('foreign_control')
        value['material_binding']={'published_path':str(parent/path.name),'stage_path':str(parent/('.preparing-'+path.name))}
        # Wholefact inputs intentionally stay ORIGINAL despite body rehash.
    payload={'format':2,'put':[[SECTIONS[0],key,value],[SECTIONS[0],'',{}]],'delete':[],'details':None}
    if damage=='marker':payload['put'].pop()
    elif damage=='duplicate':payload['put'][1]=payload['put'][0]
    elif damage=='extra':payload['put'][1]=['historical','foreign',{}]
    elif damage=='input_fact_hash':inputs['working_plan_fact_hash']='sha256:'+'0'*64
    object_id=value['request']['plan_id'] if damage!='object_id' else 'wrong_plan'
    producer='hybrid-core' if damage!='producer' else 'foreign-producer'
    previous=version-1 if damage!='previous_version' else version
    new=version if damage!='new_version' else version+1
    object_version=version if damage!='object_version' else version+1
    encoded=canonical(payload).decode() if damage!='body_noncanonical' else json.dumps(payload,indent=1)
    input_raw=canonical(inputs).decode() if damage!='noncanonical_inputs' else json.dumps(inputs,indent=1)
    payload_hash=sha(payload) if damage!='payload_hash' else '0'*64
    # This database has no actual installation/Controller context and is NOT
    # used for audit/replay/service acceptance. Direct fixture injection tests
    # only the indexed source reader's complete proof and rejection behavior.
    store=Store(tmp_path/'isolated-source-reader')
    with store.connect() as db:
        db.execute('INSERT INTO events(seq,event_id,idempotency_key,event_type,object_id,object_version,previous_state_version,new_state_version,producer,time,input_versions,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (version,'source-reader-only',key,EVENTS[0],object_id,object_version,previous,new,producer,
             value['recorded_at'],input_raw,encoded,payload_hash))
    with store.read_connection() as db:
        if damage=='none':
            assert store._working_plan_event(db,key)==((EVENTS[0],'hybrid-core',object_id,version),
                expected_objects(SECTIONS[0],key,value),event_inputs(value))
        else:
            with pytest.raises(Conflict):store._working_plan_event(db,key,max_bytes=1 if damage=='bound' else 17*1024**2)
