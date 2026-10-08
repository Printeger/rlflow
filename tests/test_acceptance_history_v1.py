import pytest
from tests.acceptance_history_v1 import measure, percentile


def test_percentile_uses_nearest_rank():
    assert percentile(list(range(1,201)))==190


def test_real_history_probe_retains_history_and_fixed_projection(tmp_path):
    result=measure(tmp_path/'probe',checkpoints=(12,24),samples=10)
    first,last=result['measurements']
    assert first['counts']['core_events']==12 and last['counts']['core_events']==24
    assert first['counts']['projection_rows']==last['counts']['projection_rows']
    assert result['summary']['full_B1_pass'] is False
    assert result['summary']['integrity']=='recover==audit==replay'


def test_probe_refuses_existing_output_and_invalid_profiles(tmp_path):
    with pytest.raises(FileExistsError):measure(tmp_path,checkpoints=(12,),samples=10)
    with pytest.raises(ValueError):measure(tmp_path/'invalid',checkpoints=(10,10),samples=10)
