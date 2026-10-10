"""Actual Linux FD data checks, never model/account/task acceptance."""
import os

import pytest

from rlflow.hybrid_native_exec_observation import _ExecFDObservation
from rlflow.store import Conflict


def inode(path):
    value=os.stat(path)
    return value.st_dev,value.st_ino


def test_actual_kernel_executable_stdio_observed_and_closed_without_starting_anything():
    pid=os.getpid();root='/proc/'+str(pid);checks=[]
    capture=_ExecFDObservation()
    value=capture.observe(pid,binary_identity=inode(root+'/exe'),
        stdout_identity=inode(root+'/fd/1'),stderr_identity=inode(root+'/fd/2'),
        check_live=lambda:checks.append(True))
    assert value['pid']==pid and len(checks)==2 and len(capture.descriptors())==3
    value['binary_identity'][0]=-1
    assert capture.value['binary_identity'][0]>=0
    with pytest.raises(Conflict):capture.observe(pid,binary_identity=inode(root+'/exe'),
        stdout_identity=inode(root+'/fd/1'),stderr_identity=inode(root+'/fd/2'),check_live=lambda:None)
    capture.close();capture.close();assert capture.descriptors()==()


@pytest.mark.parametrize('wrong',['binary','stdout','after_open'])
def test_partial_actual_observation_never_proves_wrong_image_or_stdio(wrong):
    pid=os.getpid();root='/proc/'+str(pid);capture=_ExecFDObservation();calls=[]
    def live():
        calls.append(True)
        if wrong=='after_open' and len(calls)==2:raise Conflict('original process changed')
    with pytest.raises(Conflict):capture.observe(pid,
        binary_identity=(0,0) if wrong=='binary' else inode(root+'/exe'),
        stdout_identity=(0,0) if wrong=='stdout' else inode(root+'/fd/1'),
        stderr_identity=inode(root+'/fd/2'),check_live=live)
    assert capture.value is None and capture.descriptors()
    capture.close();assert capture.descriptors()==()
