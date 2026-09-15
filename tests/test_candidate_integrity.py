"""Candidate admission regressions: untrusted Git and inode aliases cannot
become a way for the control plane to execute code or edit a source checkout.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from rlflow.policy import candidate, git
from rlflow.store import Conflict

class CandidateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rlflow-candidate-integrity-')
        self.root=Path(self.tmp.name)
        self.repo=self.root/'candidate'; self.repo.mkdir()
        self.git('init','-q')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-qm','baseline')
    def tearDown(self):self.tmp.cleanup()
    def git(self,*args):
        return subprocess.run(['/usr/bin/git','-C',str(self.repo),*args],check=True,capture_output=True,text=True)
    def test_standalone_candidate_is_accepted(self):
        self.assertEqual(candidate(self.repo)['path'],str(self.repo))
    def test_worktree_file_is_rejected(self):
        other=self.root/'worktree'
        self.git('worktree','add','--detach',str(other),'HEAD')
        with self.assertRaises(Conflict):candidate(other)
    def test_hardlinked_working_file_is_rejected(self):
        original=self.root/'protected';original.write_text('original')
        os.link(original,self.repo/'alias')
        with self.assertRaises(Conflict):candidate(self.repo)
        self.assertEqual(original.read_text(),'original')
    def test_hardlinked_git_object_is_rejected(self):
        shared=self.root/'shared-object';shared.write_text('object')
        os.link(shared,self.repo/'.git/objects/alias')
        with self.assertRaises(Conflict):candidate(self.repo)
    def test_git_metadata_symlink_is_rejected(self):
        original=self.root/'outside';original.write_text('original')
        (self.repo/'.git/info/alias').symlink_to(original)
        with self.assertRaises(Conflict):candidate(self.repo)
    def test_excluded_cache_symlink_is_rejected(self):
        cache=self.repo/'__pycache__';cache.mkdir()
        (cache/'alias').symlink_to(self.root)
        with self.assertRaises(Conflict):candidate(self.repo)
    def test_object_alternates_are_rejected(self):
        (self.repo/'.git/objects/info/alternates').write_text(str(self.root/'shared-objects')+'\n')
        with self.assertRaises(Conflict):candidate(self.repo)
    def test_fifo_is_rejected_without_opening(self):
        os.mkfifo(self.repo/'untrusted-fifo')
        with self.assertRaises(Conflict):candidate(self.repo)
    def test_control_git_does_not_run_fsmonitor(self):
        source=self.repo/'tracked';source.write_text('original');self.git('add','tracked')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','file')
        sentinel=self.root/'executed-fsmonitor'
        # The fixture only writes inside its own disposable temporary directory.
        self.git('config','core.fsmonitor',f'touch {sentinel}')
        git(self.repo,'status','--porcelain')
        self.assertFalse(sentinel.exists(),'trusted git executed repository fsmonitor config')
    def test_control_git_does_not_run_external_diff(self):
        source=self.repo/'tracked';source.write_text('original');self.git('add','tracked')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','file')
        source.write_text('changed')
        sentinel=self.root/'executed-diff'
        helper=self.root/'diff-hook';helper.write_text('#!/bin/sh\ntouch '+str(sentinel)+'\n');helper.chmod(0o700)
        self.git('config','diff.external',str(helper))
        git(self.repo,'diff','HEAD')
        self.assertFalse(sentinel.exists(),'trusted git executed repository external diff config')

if __name__=='__main__':unittest.main()
