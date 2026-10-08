import json
import pytest
from rlflow.hybrid_protocol import ProtocolError, validate
from rlflow.observation import ObservationReader, enable, public_id, rotate_epoch
from rlflow.public_logs import body, page
from rlflow.store import Store


@pytest.fixture
def observed(tmp_path):
    store = Store(tmp_path / "state")
    enable(store,"project_logs",data_mode="fixture")
    return store,ObservationReader(store.root,expected_project_id="project_logs",expected_data_mode="fixture")


def update(store, key, **fields):
    store.transact_objects("LOG_TEST",key,[("usage","usage1")],lambda s:s.setdefault("usage",{}).update(usage1=fields))


def test_only_closed_status_templates_and_lazy_summary(observed):
    store,reader = observed
    update(store,"new",status='FAKE_PRIVATE_REASONING <img onerror=alert(1)>',reason="secret",description="PRIVATE_OUTPUT",input_tokens=8)
    result = page(reader)
    validate("LogPage",result)
    summary = result["items"][0]
    assert "text" not in summary and summary["source"] == "CORE_STATUS"
    detail = body(reader,summary["id"])
    validate("LogBody",detail)
    assert "observed state UNKNOWN" in detail["text"]
    for value in ("PRIVATE_REASONING","<img","secret","PRIVATE_OUTPUT"):
        assert value not in json.dumps(detail)
    assert detail["refs"] == [{"kind":"usage","id":public_id("usage1"),"version":1}]
    assert detail["raw_logs"] == "PRIVATE_ONLY" and detail["tool_metadata"] == "UNAVAILABLE"
    update(store,"new",status="IGNORED")
    assert page(reader) == result


def test_high_water_prevents_live_insert_duplicates_and_filter_changes(observed):
    store,reader = observed
    for index in range(5): update(store,str(index),input_tokens=index,status="FAILED" if index%2 else "WAITING")
    first = page(reader,limit=2)
    high = first["high_water"]
    update(store,"late",input_tokens=99)
    second = page(reader,limit=2,after=first["next_cursor"])
    assert second["high_water"] == high
    third = page(reader,limit=2,after=second["next_cursor"])
    sequences = [r["seq"] for p in (first,second,third) for r in p["items"]]
    assert sequences == list(range(6,0,-1))
    with pytest.raises(ProtocolError): page(reader,after=first["next_cursor"],severity="ERROR")
    errors = page(reader,severity="ERROR")
    assert len(errors["items"]) == 2 and all(r["severity"] == "ERROR" for r in errors["items"])


def test_rollback_logs_and_source_outbox_together(observed, monkeypatch):
    from rlflow import public_logs
    store,reader = observed
    before = reader.snapshot()
    logs = page(reader)
    original = public_logs.build
    def reject(event): raise ProtocolError("injected log failure")
    monkeypatch.setattr(public_logs,"build",reject)
    with pytest.raises(ProtocolError): update(store,"bad",input_tokens=1)
    monkeypatch.setattr(public_logs,"build",original)
    assert reader.snapshot()["cursor"] == before["cursor"] and page(reader) == logs
    assert store.version() == 0 and store.get("usage","usage1") is None


def test_read_only_upgrade_is_explicit_and_coverage_truthful(observed):
    store,reader = observed
    with store.connect() as db:
        # Simulate old observer schema; no production destructive upgrade path.
        db.execute("DROP TABLE public_log_refs"); db.execute("DROP TABLE public_logs"); db.execute("DROP TABLE public_log_meta"); db.commit()
    update(store,"old",input_tokens=1)
    with pytest.raises(ProtocolError) as error: page(reader)
    assert error.value.code == "UNSUPPORTED_CAPABILITY"
    epoch = reader.head()["cursor"].rsplit(":",1)[0]
    assert enable(store,"project_logs",data_mode="fixture") == epoch
    assert page(reader)["items"] == [] and page(reader)["coverage_after_seq"] == 2
    update(store,"upgraded",input_tokens=2)
    assert len(page(reader)["items"]) == 1
    assert page(reader)["items"][0]["seq"] == 3


def test_epoch_scope_identity_and_missing_body_fail_closed(observed):
    store,reader = observed
    update(store,"one",input_tokens=1)
    current = page(reader,limit=1)
    log_id = current["items"][0]["id"]
    assert current["next_cursor"]
    for expected in ({"expected_project_id":"other"},{"expected_data_mode":"live"}):
        wrong = ObservationReader(store.root,**expected)
        for call in (lambda: page(wrong),lambda: body(wrong,log_id)):
            with pytest.raises(ProtocolError): call()
    with pytest.raises(ProtocolError) as error: body(reader,"not_found")
    assert error.value.code == "NOT_FOUND"
    rotate_epoch(store)
    with pytest.raises(ProtocolError): page(reader,after=current["next_cursor"])
    with pytest.raises(ProtocolError): body(reader,log_id)
    assert page(reader)["items"] == []
    update(store,"after_epoch",input_tokens=3)
    assert len(page(reader)["items"]) == 1


@pytest.mark.parametrize("target",["summary","body","source","ref"])
def test_corrupt_log_material_is_rejected(observed,target):
    store,reader = observed
    update(store,"one",input_tokens=1)
    log_id = page(reader)["items"][0]["id"]
    with store.connect() as db:
        if target in {"summary","body"}:
            db.execute("DROP TRIGGER public_logs_no_update")
            db.execute(f"UPDATE public_logs SET {target}='{{}}' WHERE log_id=?",(log_id,))
        elif target == "source":
            db.execute("DROP TRIGGER observation_no_update")
            db.execute("UPDATE observation_events SET envelope='{}' WHERE seq=2")
        else:
            db.execute("DROP TRIGGER public_logs_no_delete")
            db.execute("DELETE FROM public_logs WHERE seq=2")
        db.commit()
    with pytest.raises(ProtocolError): body(reader,log_id)


@pytest.mark.parametrize("arguments",[{"limit":0},{"limit":201},{"limit":True},{"severity":"debug"},{"kind":"task"},
    {"object_id":"id"},{"kind":"stage","object_id":"id"},{"after":"bad"},{"kind":"task","object_id":"../private"}])
def test_invalid_queries_rejected(observed,arguments):
    with pytest.raises(ProtocolError): page(observed[1],**arguments)


def test_indexed_reference_filter_and_body_has_no_raw_private_read(observed,monkeypatch):
    from pathlib import Path
    store,reader = observed
    value = {"status":"FAILED","task_id":"task1"}
    # Existing usage objects permit relation metadata; experiment persistence is
    # not implemented yet and this test must not relax RuntimeState for it.
    update(store,"related",**value)
    selected = page(reader,kind="task",object_id=public_id("task1"),severity="ERROR")
    assert len(selected["items"]) == 1
    assert page(reader,kind="experiment",object_id=public_id("experiment1"))["items"] == []
    assert page(reader,kind="execution",object_id=public_id("usage1"))["items"] == []
    def forbidden(*a,**kw): raise AssertionError("no raw file read permitted")
    monkeypatch.setattr(Path,"read_text",forbidden);monkeypatch.setattr(Path,"read_bytes",forbidden)
    assert body(reader,selected["items"][0]["id"])["summary"] == selected["items"][0]


def test_filtered_keyset_query_uses_reference_range_index(observed,monkeypatch):
    store,reader = observed
    update(store,"related",status="FAILED",task_id="task1")
    statements = []
    original = reader.connect
    def traced():
        db = original(); db.set_trace_callback(statements.append); return db
    monkeypatch.setattr(reader,"connect",traced)
    page(reader,kind="task",object_id=public_id("task1"),severity="ERROR")
    query = next(sql for sql in statements if sql.startswith("SELECT l.seq,l.log_id"))
    with original() as db:
        plan = [r["detail"] for r in db.execute("EXPLAIN QUERY PLAN " + query)]
    assert any("public_log_refs_severity" in line for line in plan), plan
    assert not any("SCAN " in line or "TEMP B-TREE" in line for line in plan), plan


def test_split_large_commit_keeps_every_log_bounded(observed):
    store,reader = observed
    keys = [f"usage_{index}" for index in range(301)]
    store.transact_objects("USAGE_BATCH","batch",[("usage",key) for key in keys],
                           lambda s:s.setdefault("usage",{}).update({key:{"input_tokens":1,"task_id":key} for key in keys}))
    result = page(reader)
    entries = [entry for entry in result["items"] if entry["object_count"]]
    assert sum(entry["object_count"] for entry in entries) == 301
    assert len(entries) == 2
    for entry in entries:
        detail = body(reader,entry["id"])
        assert len(detail["text"].encode()) < 65536 and len(detail["refs"]) <= 600


def test_index_entry_cannot_forge_reference_even_for_same_project(observed):
    store,reader = observed
    update(store,"related",status="FAILED",task_id="task1")
    with store.connect() as db:
        db.execute("DROP TRIGGER public_log_refs_no_update")
        db.execute("UPDATE public_log_refs SET object_id=? WHERE kind='task'",(public_id("task_other"),));db.commit()
    with pytest.raises(ProtocolError,match="reference mismatch"):
        page(reader,kind="task",object_id=public_id("task_other"))


def test_inserted_reference_cannot_change_object_or_severity(observed):
    import sqlite3
    store,reader = observed
    update(store,"related",status="FAILED",task_id="task1")
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError,match="reference source mismatch"):
            db.execute("INSERT INTO public_log_refs VALUES('task',?,2,'INFO')",(public_id("unrelated"),))
        # Explicit fixture corruption bypasses insertion and immutable guards;
        # normal writes cannot create this index lie.
        db.execute("DROP TRIGGER public_log_refs_insert_guard")
        db.execute("INSERT INTO public_log_refs VALUES('task',?,2,'INFO')",(public_id("unrelated"),))
        db.execute("DROP TRIGGER public_log_refs_no_update")
        db.execute("UPDATE public_log_refs SET severity='INFO' WHERE object_id=?",(public_id("task1"),));db.commit()
    for object_id in (public_id("unrelated"),public_id("task1")):
        with pytest.raises(ProtocolError,match="reference mismatch"):
            page(reader,kind="task",object_id=object_id,severity="INFO")


def test_middle_history_gap_does_not_hide_behind_max_seq(observed):
    store,reader = observed
    for index in range(3): update(store,str(index),input_tokens=index,task_id="task1")
    with store.connect() as db:
        db.execute("DROP TRIGGER public_logs_no_delete");db.execute("DELETE FROM public_logs WHERE seq=2");db.commit()
    for arguments in ({},{"kind":"task","object_id":public_id("task1")}):
        with pytest.raises(ProtocolError,match="sequence gap|missing indexed"):
            page(reader,**arguments)


@pytest.mark.parametrize("missing",["public_log_refs","public_logs","public_log_meta"])
def test_prepare_cannot_silently_recreate_partial_log_schema(observed,missing):
    store,reader = observed
    update(store,"related",status="FAILED",task_id="task1")
    with store.connect() as db:
        db.execute(f"DROP TABLE {missing}"); db.commit()
    with pytest.raises(ProtocolError,match="partial public log schema"):
        enable(store,"project_logs",data_mode="fixture")
    with pytest.raises(ProtocolError,match="partial public log schema"):
        page(reader)
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(missing,)).fetchone() is None
    assert store.version() == 1
