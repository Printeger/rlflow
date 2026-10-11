"""Original prepared fixture events, no model/G/account input or CPU task."""
import pytest

from rlflow.hybrid_fixture_runtime_ledger import dependency_lookup
from rlflow.hybrid_preparation import SECTIONS as PREPARATION
from rlflow.hybrid_reads import ReadBudget
from rlflow.store import Conflict,PREPARATION_READ_BYTES
from tests.test_hybrid_a_workflow_derivation import original,native_setup


def test_same_projection_cannot_replace_preparation_original_events_or_sources(original):
    owner,bundle,token,obs,_=original
    _,ready=owner._plan_original(bundle,token,obs)
    refs=ready['source_context']['preparation']
    with owner.store.connect() as db:
        db.execute('BEGIN');lookup=dependency_lookup(owner.store,db,ReadBudget(db,PREPARATION_READ_BYTES),{})
        intent=lookup(PREPARATION[0],refs['intent_key'])
        outcome=lookup(PREPARATION[1],refs['result_key'])
        assert intent is not None and outcome is not None
        db.rollback()
        # Isolated fixture mutations are rolled back; projection is unchanged.
        for fault in ('missing_intent','corrupt_result','missing_intent_source'):
            db.execute('BEGIN')
            try:
                if fault=='corrupt_result':
                    db.execute('DROP TRIGGER no_update')  # This isolated rollback fixture only.
                    db.execute('UPDATE events SET payload_sha256=? WHERE idempotency_key=?',
                        ('0'*64,refs['result_key']))
                    section,key=PREPARATION[1],refs['result_key'];expected=outcome
                else:
                    db.execute('DROP TRIGGER no_delete')  # Restored by the transaction rollback.
                    event=refs['intent_key'] if fault=='missing_intent' else intent['sources']['draft_command_key']
                    db.execute('DELETE FROM events WHERE idempotency_key=?',(event,))
                    section,key=PREPARATION[0],refs['intent_key'];expected=intent
                read=ReadBudget(db,PREPARATION_READ_BYTES)
                assert read.object(section,key)==expected
                lookup=dependency_lookup(owner.store,db,read,{})
                with pytest.raises(Conflict):lookup(section,key)
            finally:db.rollback()
