import pytest
from rlflow.store import Store, Conflict
from rlflow.migration import import_history

def test_project_history_cannot_be_imported(tmp_path):
    store = Store(tmp_path/'state')
    before = store.replay()
    with pytest.raises(Conflict, match='excluded'):
        import_history(store)
    assert store.replay() == before
