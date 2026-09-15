import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from rlflow import jobs


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stop = self.root / 'STOP'

    def tearDown(self):
        self.stop.touch()
        for child in jobs._CHILDREN:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                jobs._kill_owned(jobs.identity(child.pid))
                child.wait(timeout=3)
        jobs._CHILDREN.clear()
        self.tmp.cleanup()

    def submit(self, spec=None):
        return jobs.submit(self.root, 'j1', spec or {}, [str(self.stop)])

    def wait(self, wanted=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = jobs.status(self.root, 'j1')
            if state['state'] in (wanted or jobs.TERMINAL | {'RECONCILE'}):
                return state
            time.sleep(.01)
        self.fail('job did not reach expected state: ' + str(state))

    def test_success_idempotent_and_bound_content(self):
        first = self.submit()
        result = self.wait()
        self.assertEqual(result['state'], 'SUCCEEDED')
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['released'])
        self.assertEqual(self.submit()['nonce'], first['nonce'])
        self.assertEqual(self.submit()['start_attempts'], 1)
        with self.assertRaises(ValueError):
            self.submit({'duration': 1})
        self.assertEqual(jobs.reconcile(self.root, 'j1'), result)

    def test_no_message_and_partial_message_bounded(self):
        for mode in ('no_message', 'partial_message'):
            with self.subTest(mode=mode):
                root = self.root / mode
                start = time.monotonic()
                jobs.submit(root, 'j1', {'mode': mode, 'handshake_timeout': .15}, [str(self.stop)])
                while jobs.status(root, 'j1')['state'] not in jobs.TERMINAL:
                    self.assertLess(time.monotonic() - start, 3)
                    time.sleep(.01)
                result = jobs.status(root, 'j1')
                self.assertEqual(result['state'], 'HANDSHAKE_TIMEOUT')
                self.assertFalse(jobs.owns(result['child']))
                self.assertFalse(result['released'])

    def test_short_lived(self):
        self.submit({'mode': 'short_lived'})
        self.assertEqual(self.wait()['state'], 'FAILED')

    def test_stop_before_dispatch(self):
        self.stop.touch()
        result = self.submit()
        self.assertEqual(result['state'], 'STOPPED')
        self.assertEqual(result['start_attempts'], 0)
        self.assertNotIn('child', result)
        self.assertIn(str(jobs.CANONICAL_STOP), result['stop_paths'])

    def test_stop_during_handshake(self):
        self.submit({'mode': 'no_message'})
        self.wait({'HANDSHAKE'})
        self.stop.touch()
        result = self.wait()
        self.assertEqual(result['state'], 'STOPPED')
        self.assertFalse(result['released'])
        self.assertFalse(jobs.owns(result['child']))

    def test_stop_before_release(self):
        self.submit({'before_release_delay': .3})
        self.wait({'HELD'})
        self.stop.touch()
        result = self.wait()
        self.assertEqual(result['state'], 'STOPPED')
        self.assertFalse(result['released'])

    def test_stop_running(self):
        self.submit({'duration': 2})
        self.wait({'RUNNING'})
        self.stop.touch()
        result = self.wait()
        self.assertEqual(result['state'], 'STOPPED')
        self.assertTrue(result['released'])
        self.assertFalse(jobs.owns(result['child']))

    def test_unrelated_process_and_pid_reuse(self):
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'], start_new_session=True)
        try:
            real = jobs.identity(other.pid)
            self.assertFalse(jobs._kill_owned(dict(real, starttime='invalid')))
            self.assertIsNone(other.poll())
            self.assertFalse(jobs._kill_owned(dict(real, pgid=os.getpgrp())))
            self.assertIsNone(other.poll())
        finally:
            other.kill()
            other.wait()

    def test_restart_lost_supervisor_never_restarts(self):
        self.submit({'duration': .5})
        state = self.wait({'RUNNING'})
        os.kill(state['supervisor']['pid'], signal.SIGKILL)
        time.sleep(.04)
        recovered = jobs.reconcile(self.root, 'j1')
        self.assertEqual(recovered['state'], 'RECONCILE')
        self.assertEqual(self.submit({'duration': .5})['nonce'], state['nonce'])
        self.assertEqual(recovered['start_attempts'], 1)
        time.sleep(.55)
        final = jobs.reconcile(self.root, 'j1')
        self.assertEqual(final['state'], 'RECONCILE')
        self.assertEqual(final['reconciliation']['result_artifact'], 'identity_matches')
        self.assertFalse(final['reconciliation']['exit_evidence_available'])

    def test_client_exit_preserves_supervision(self):
        script = ('from pathlib import Path; from rlflow.jobs import submit; '
                  'submit(Path(' + repr(str(self.root)) + '), "j1", {"duration": .2}, [' + repr(str(self.stop)) + '])')
        subprocess.run([sys.executable, '-c', script], check=True)
        self.assertEqual(self.wait()['state'], 'SUCCEEDED')

    def test_unknown_start_intent_preserved(self):
        path = self.root / 'jobs' / 'j1'
        path.mkdir(parents=True)
        jobs._dump(path / 'state.json', {'state': 'START_INTENT', 'start_attempts': 1})
        self.assertEqual(jobs.reconcile(self.root, 'j1')['state'], 'RECONCILE')
        self.assertEqual(jobs.status(self.root, 'j1')['start_attempts'], 1)

    def test_fail_and_invalid_backend(self):
        self.submit({'mode': 'fail'})
        self.assertEqual(self.wait()['exit_code'], 9)
        for spec in ({'backend': 'gpu'}, {'command': 'true'}, {'duration': True}, {'duration': float('nan')}):
            with self.assertRaises(ValueError):
                jobs.submit(self.root, 'bad', spec)
        with self.assertRaises(ValueError):
            jobs.submit(self.root, '../bad', {})


if __name__ == '__main__':
    unittest.main()
