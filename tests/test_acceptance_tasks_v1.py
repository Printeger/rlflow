import pytest
from tests.acceptance_tasks_v1 import measure


def test_real_tasks_probe_keeps_history_and_no_work_does_not_dispatch(tmp_path):
    result=measure(tmp_path/'probe',sizes=(2,5),samples=2)
    assert result['full_B1_pass'] is False
    assert [r['counts']['core_events'] for r in result['measurements']]==[5,5]
    assert [r['counts']['task_rows'] for r in result['measurements']]==[2,5]


def test_probe_refuses_existing_output_and_invalid_profiles(tmp_path):
    with pytest.raises(FileExistsError):measure(tmp_path,sizes=(2,),samples=2)
    with pytest.raises(ValueError):measure(tmp_path/'invalid',sizes=(2,2),samples=2)


@pytest.mark.parametrize('module',['acceptance_tasks_v1','acceptance_history_v1'])
def test_optimized_interpreter_cannot_omit_acceptance_work(tmp_path,module):
    import subprocess,sys
    output=tmp_path/'never-created'
    result=subprocess.run([sys.executable,'-O','-m','tests.'+module,str(output)],capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and 'optimized Python is unsupported' in result.stderr
    assert not output.exists()
