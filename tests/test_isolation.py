import json
from pathlib import Path
import shlex
import tempfile
import os
import signal
import shutil
import subprocess
import sys
import time
import unittest
from rlflow.isolation import cpu_exec, doctor, IsolationError, codex_command, require_doctor

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rlflow-isolation-test-')
        self.root=Path(self.tmp.name)
        self.c=self.root/'candidate';self.s=self.root/'scratch';self.p=self.root/'protected'
        for p in (self.c,self.s,self.p):p.mkdir()
        self.secret=self.p/'sentinel';self.secret.write_text('untouched')
    def tearDown(self): self.tmp.cleanup()
    def run_cpu(self,script,role='Engineer',timeout=3):
        return cpu_exec('/usr/bin/python3 -c '+shlex.quote(script),self.c,self.s,role,timeout=timeout)
    def test_six_roles_interfaces_and_scope(self):
        for role in ('PI','Critic','Designer','Engineer','Evaluator','Scout'):
            r=self.run_cpu(f"from pathlib import Path; Path({str(self.s/'owned')!r}).write_text('ok'); Path({str(self.c/'source')!r}).write_text('ok')",role)
            self.assertEqual(r['exit_code']==0,role=='Engineer',r)
    def test_read_write_symlink_and_metadata_denied(self):
        (self.c/'escape').symlink_to(self.p,target_is_directory=True)
        before=self.secret.stat()
        for expression in [f"open({str(self.secret)!r}).read()", f"open({str(self.secret)!r},'w')",f"open({str(self.c/'escape'/'sentinel')!r},'w')",f"os.chmod({str(self.secret)!r},0)",f"os.utime({str(self.secret)!r},(0,0))"]:
            r=self.run_cpu('import os; '+expression)
            self.assertNotEqual(r['exit_code'],0,r)
        self.assertEqual(self.secret.read_text(),'untouched')
        self.assertEqual(self.secret.stat().st_mode,before.st_mode)
        self.assertEqual(self.secret.stat().st_mtime_ns,before.st_mtime_ns)
    def test_control_network_nested_agent_proc_denied(self):
        for expression in ["socket.socket()", "os.kill(os.getppid(),0)","open('/proc/self/environ').read()", "subprocess.run(['/usr/local/bin/codex','--version'])", "os.setsid()"]:
            r=self.run_cpu('import os,socket,subprocess; '+expression)
            self.assertNotEqual(r['exit_code'],0,r)
    def test_auth_read_denied(self):
        auth=self.p/'auth.json'
        auth.write_text('{"token":"synthetic-test-only"}')
        r=self.run_cpu(f"open({str(auth)!r}).read()")
        self.assertNotEqual(r['exit_code'],0)
        self.assertIn('PermissionError',r['stderr'])
    def test_timeout(self):
        r=self.run_cpu('import time; time.sleep(20)',timeout=0.1)
        self.assertTrue(r['timed_out']);self.assertLess(r['wall_seconds'],5)
    def test_invalid_configuration_fails_closed(self):
        for args in [('Unknown',self.c,self.s),('Engineer',self.c,self.c)]:
            with self.assertRaises(IsolationError): cpu_exec('true',args[1],args[2],args[0])
        with self.assertRaises(IsolationError):cpu_exec('true',self.c,self.s,'Engineer',write_roots=[str(self.p)])
    def test_output_cannot_be_role_writable(self):
        with self.assertRaises(IsolationError):codex_command('Engineer',self.c,self.s,self.p/'schema',self.c/'result')
    def test_cpu_tools_remain_usable(self):
        r=cpu_exec('git --version && /usr/bin/python3 -c "import json,unittest; print(42)"',self.c,self.s,'Engineer')
        self.assertEqual(r['exit_code'],0,r);self.assertIn('42',r['stdout'])
    def test_module_write_root_and_read_only_extra_executable_are_enforced(self):
        writable=self.c/'module';writable.mkdir()
        frozen=self.c/'evidence';frozen.mkdir();(frozen/'record').write_text('sealed')
        runtime=self.root/'runtime';runtime.mkdir()
        tool=runtime/'probe';shutil.copy2('/usr/bin/true',tool)
        command=(f"{tool} && echo cpu-runtime-ok && echo changed > {writable/'result'} && "
                 f"echo forbidden > {frozen/'record'}")
        r=cpu_exec(command,self.c,self.s,'Engineer',read_extra=[str(runtime)],
                   write_roots=[str(writable)],execute_extra=[str(runtime)])
        self.assertNotEqual(r['exit_code'],0,r)
        self.assertTrue((writable/'result').is_file())
        self.assertEqual((frozen/'record').read_text(),'sealed')
        self.assertIn('cpu-runtime-ok',r['stdout'])
    def test_doctor_report_binds_implementation(self):
        report=doctor(self.root/'state')
        self.assertTrue(report['ok'],report)
        self.assertEqual(require_doctor(self.root/'state')['isolation_sha256'],report['isolation_sha256'])
        report['isolation_sha256']='changed'
        (self.root/'state/runtime/doctor.json').write_text(json.dumps(report))
        with self.assertRaises(IsolationError):require_doctor(self.root/'state')
    def test_supervisor_cleans_descendants_when_owner_dies(self):
        marker=self.s/'pids'
        inner="import subprocess,os,time; p=subprocess.Popen(['/usr/bin/python3','-c','import time; time.sleep(30)']); open("+repr(str(marker))+",'w').write(str(os.getpid())+' '+str(p.pid)); time.sleep(30)"
        cmd='/usr/bin/python3 -c '+shlex.quote(inner)
        caller="from rlflow.isolation import cpu_exec; cpu_exec("+repr(cmd)+','+repr(str(self.c))+','+repr(str(self.s))+",'Engineer',timeout=60)"
        parent=subprocess.Popen([sys.executable,'-c',caller],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+4
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(marker.exists(),'CPU command did not start')
            pids=[int(p) for p in marker.read_text().split()]
            parent.kill();parent.wait()
            def running(pid):
                try:return Path('/proc/'+str(pid)+'/stat').read_text().split()[2] not in ('Z','X')
                except FileNotFoundError:return False
            deadline=time.monotonic()+3
            while any(running(p) for p in pids) and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(any(running(p) for p in pids),'Owned descendants survived supervisor owner death')
        finally:
            if parent.poll() is None:parent.kill();parent.wait()
    def test_doctor_real_kernel(self):
        r=doctor();self.assertTrue(r['ok'],r)

if __name__=='__main__':unittest.main()
