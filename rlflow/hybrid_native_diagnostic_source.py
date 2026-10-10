"""Original native CLI stdout, separate sandbox receipt and held local receiver.

Receiver requests are observations only, NEVER PID/token/started/terminal proof.
"""
import hashlib
import http.server
import json
import os
import socket
from pathlib import Path
import threading
import time

from .hybrid_fixture_materials import _write_new
from .hybrid_goals import digest
from .hybrid_usage_source import (FixtureUsageSourceOwner,SOURCE_FILES,
    FixtureUsageSource,SourceObservation,_RuntimeStartedObservation,POLL_BYTES,POLL_LINES,POLL_NODES)
from .hybrid_runtime_boundary import directory_chain
from .hybrid_native_diagnostic_gate import native_command
from .hybrid_usage_stream import parse_line
from .jobs import identity
from .store import Conflict,canonical


class NativeDiagnosticSourceOwner(FixtureUsageSourceOwner):
    def __init__(self,pool):
        self._ready_receipts={}
        super().__init__(pool)

    def _actual(self):
        from . import hybrid_usage_source
        if type(self) is not NativeDiagnosticSourceOwner or hybrid_usage_source._owners.get(id(self)) is not self:
            raise PermissionError('actual original registered native source owner required')
        super()._actual()

    def start_fixture(self,*args,**kwargs):raise PermissionError('closed original diagnostic source only')

    def _source_files(self):
        return {**SOURCE_FILES,'ready_read':'sandbox.jsonl','ready_write':'sandbox.jsonl','config':'launch.json'}

    def _check_binary(self,attempt):
        from .hybrid_native_diagnostic import check_binary
        row=attempt['binary'];row['fd']=attempt['fds']['binary'];check_binary(row)
        if attempt.get('native_allocated') and list(row['stamp'])!=json.loads(attempt['source'].raw)['native_binding']['binary_stamp']:
            raise Conflict('original immutable native ELF identity differs')

    def _sandbox_ready(self,source):
        self._issued(source)
        return self._ready_receipts.get(id(source))

    def _physical(self,attempt):
        accepted=attempt.get('accepted')
        if accepted is not None and accepted[1] is None:
            raise Conflict('original receiver connection identity UNKNOWN; no new effect')
        result=super()._physical(attempt)
        if attempt.get('native_allocated'):
            binding=json.loads(attempt['source'].raw)['native_binding']
            if (hashlib.sha256(attempt['config_raw']).hexdigest()!=binding['config_sha256'] or
                    os.pread(attempt['fds']['config'],32769,0)!=attempt['config_raw'] or
                    directory_chain(attempt['path']/'auth-empty')!=binding['home_chain'] or
                    directory_chain(attempt['path']/'work')!=binding['work_chain']):
                raise Conflict('original immutable native source/config/namespace binding differs')
            server=attempt.get('server')
            if server is None or server.socket.fileno()<0 or os.get_inheritable(server.socket.fileno()):
                raise Conflict('original native receiver listener unavailable')
            info=os.fstat(server.socket.fileno())
            if [info.st_dev,info.st_ino]!=binding['receiver_identity'] or list(server.server_address)!=binding['receiver_address']:
                raise Conflict('original native receiver rebound')
        return result

    def _runtime_allocate(self,owner,lease):
        from .hybrid_native_diagnostic import NativeDiagnosticOwner,pin_binary
        if type(owner) is not NativeDiagnosticOwner or type(self) is not NativeDiagnosticSourceOwner:
            raise PermissionError('closed original native diagnostic source owner required')
        source=super()._runtime_allocate(owner,lease);attempt=self._issued(source)
        with self._lock:
            if attempt.get('native_allocated'):return source
            if attempt.get('native_allocation_entered'):raise Conflict('original native allocation UNKNOWN; no replacement')
            attempt['native_allocation_entered']=True
            try:
                row=pin_binary();attempt['binary']=row;attempt['fds']['binary']=row['fd']
                if row['sha256']!=owner._issued(lease)['origin']['native_diagnostic']['binary_sha256']:
                    raise Conflict('original approved native binary differs')
                home=attempt['path']/'auth-empty';work=attempt['path']/'work'
                home.mkdir(mode=0o700);work.mkdir(mode=0o700)
                attempt['held']=threading.Event();attempt['received']=threading.Event();attempt['receiver_requests']=0
                attempt['receiver_lock']=threading.RLock();attempt['receiver_stop']=threading.Event()
                attempt['accepted']=None
                attempt['sandbox_receipt']=None;attempt['config_raw']=None
                class Receiver(http.server.BaseHTTPRequestHandler):
                    def do_POST(handler):
                        handler.connection.settimeout(2)
                        try:
                            length=int(handler.headers.get('Content-Length','-1'))
                            if not 0<=length<=1024**2:raise ValueError('bounded local request required')
                            raw=handler.rfile.read(length)
                            if len(raw)!=length:raise ValueError('incomplete local request')
                            attempt['receiver_requests']+=1;attempt['received'].set()
                            attempt['held'].wait(20)
                            handler.send_response(400);handler.end_headers()
                            handler.wfile.write(b'{"error":{"message":"local diagnostic only; no model exists"}}')
                        except (OSError,ValueError):pass
                    def log_message(handler,*args):pass
                class Server(http.server.HTTPServer):
                    def get_request(server):
                        with attempt['receiver_lock']:
                            if attempt['receiver_stop'].is_set():raise OSError('original receiver stopped')
                            # Accept and original FD registration are one fork
                            # atomic segment. The listener has a finite timeout.
                            connection,address=super().get_request()
                            attempt['accepted']=(connection,None)
                            try:
                                info=os.fstat(connection.fileno())
                                attempt['accepted']=(connection,(info.st_dev,info.st_ino))
                                if attempt['receiver_stop'].is_set():
                                    connection.close();raise OSError('original receiver stopped')
                                connection.settimeout(2)  # Also bounds initial header waiting.
                            except BaseException:
                                # BaseServer swallows get_request OSError. Stop
                                # its loop so another accept cannot overwrite
                                # an unknown original participant.
                                attempt['status']='UNKNOWN';attempt['receiver_stop'].set()
                                raise
                        return connection,address
                    def handle_error(server,*args):pass
                attempt['receiver_creation_entered']=True
                server=Server(('127.0.0.1',0),Receiver)
                # Retain the original participant before any fallible FD IO.
                attempt['server']=server
                info=os.fstat(server.socket.fileno())
                attempt['listener_identity']=(info.st_dev,info.st_ino)
                server.socket.settimeout(.05)
                server.timeout=.05
                def serve():
                    while not attempt['receiver_stop'].is_set():
                        try:server.handle_request()
                        except OSError:break
                thread=threading.Thread(target=serve,daemon=True)
                attempt['server_thread']=thread;thread.start()
                catalog={'models':[{'slug':'rlflow-local-non-generating','display_name':'Local non-model diagnostic',
                    'supported_reasoning_levels':[{'effort':'medium','description':'Local diagnostic'}],
                    'visibility':'list','supported_in_api':True,'priority':1,'support_verbosity':True,
                    'truncation_policy':{'mode':'tokens','limit':10000},
                    'base_instructions':'Local non-generating diagnostic only.','use_responses_lite':True,
                    'shell_type':'disabled','apply_patch_tool_type':None,'experimental_supported_tools':[],
                    'supports_search_tool':False,'include_skills_usage_instructions':False,
                    'include_plugin_usage_instructions':False,'include_apps_usage_instructions':False,
                    'tool_mode':'direct','multi_agent_version':'disabled'}]}
                _write_new(home/'catalog.json',canonical(catalog))
                argv,env=native_command(str(home),str(work),server.server_port)
                raw=canonical({'home':str(home),'work':str(work),'port':server.server_port,'argv':argv,'env':env})
                attempt['config_raw']=raw
                for name,content in (('sandbox.jsonl',b''),('launch.json',raw)):_write_new(attempt['path']/name,content)
                for key,name,flags in (('ready_read','sandbox.jsonl',os.O_RDONLY),
                        ('ready_write','sandbox.jsonl',os.O_WRONLY|os.O_APPEND),('config','launch.json',os.O_RDONLY)):
                    fd=os.open(attempt['path']/name,flags|os.O_NOFOLLOW|os.O_CLOEXEC)
                    attempt['fds'][key]=fd;info=os.fstat(fd);attempt['identities'][name]=[info.st_dev,info.st_ino]
                # Immutable original issued source, distinct from mutable rows.
                # No source cap escaped allocation yet; the first provisional
                # source is retired, never upgraded after a caller has it.
                binding=json.loads(source.raw);info=os.fstat(server.socket.fileno())
                binding['native_binding']={'config_sha256':hashlib.sha256(raw).hexdigest(),
                    'binary_stamp':list(row['stamp']),
                    'home_chain':directory_chain(home),'work_chain':directory_chain(work),
                    'receiver_identity':[info.st_dev,info.st_ino],'receiver_address':list(server.server_address)}
                original=FixtureUsageSource(source.id,canonical(binding))
                self._sources.pop(id(source));attempt['source']=original;self._sources[id(original)]=attempt
                attempt['native_allocated']=True;self._physical(attempt)
                return original
            except BaseException:
                attempt['status']='UNKNOWN';raise

    def _native_spawn_material(self,owner,attempt):
        self._check_binary(attempt)
        if os.pread(attempt['fds']['config'],32769,0)!=attempt['config_raw']:
            raise Conflict('original native launch config changed')
        return tuple(attempt['fds'][k] for k in ('binary','ready_write','config'))

    def _wait_ready(self,owner,attempt):
        deadline=time.monotonic()+2
        binding=json.loads(attempt['source'].raw)['native_binding']
        expected={'type':'diagnostic.sandbox.ready','pid':attempt['producer_identity']['pid'],
            'nonce':attempt['runtime']['origin']['nonce'],
            'config_sha256':binding['config_sha256'],
            'binary_identity':binding['binary_stamp'][:2],
            'binary_sha256':attempt['runtime']['origin']['native_diagnostic']['binary_sha256'],
            'home_identity':binding['home_chain'][-1][:2]+[os.geteuid(),0o700],
            'work_identity':binding['work_chain'][-1][:2]+[os.geteuid(),0o700],
            'single_tgid':True,'landlock':True,'no_new_privs':True,'network_enforcement':'PARTIAL'}
        while time.monotonic()<deadline:
            self._physical(attempt);raw=os.pread(attempt['fds']['ready_read'],4097,0)
            if raw:
                if raw!=canonical(expected)+b'\n':raise Conflict('original sandbox receipt differs')
                attempt['sandbox_receipt']=expected
                self._ready_receipts[id(attempt['source'])]=SourceObservation(attempt['source'],canonical(expected))
                return
            if attempt['producer'].poll() is not None:break
            time.sleep(.01)
        raise Conflict('original native sandbox not ready; no G')

    def _runtime_release(self,owner,lease):
        attempt=self._issued(owner._issued(lease)['source'])
        ready=self._sandbox_ready(attempt['source'])
        if ready is None:raise Conflict('original sandbox receipt required before G')
        if os.pread(attempt['fds']['ready_read'],4097,0)!=ready.raw+b'\n':
            raise Conflict('original sandbox receipt changed')
        return super()._runtime_release(owner,lease)

    def poll(self,source):
        attempt=self._issued(source)
        with self._lock:
            if attempt['status'] in ('UNKNOWN','QUARANTINED','CLOSED'):return self._observation(attempt)
            try:
                stamp=self._physical(attempt);old=attempt['seen'];fd=attempt['fds']['read']
                if old is not None and (stamp[0]<old[0] or stamp[0]==old[0] and stamp!=old):
                    raise Conflict('native original stdout changed without append')
                if attempt['anchor'] and os.pread(fd,len(attempt['anchor']),attempt['offset']-len(attempt['anchor']))!=attempt['anchor']:
                    raise Conflict('native original prefix changed')
                if attempt['tail'] and os.pread(fd,len(attempt['tail']),attempt['offset'])!=attempt['tail']:
                    raise Conflict('native original partial tail changed')
                raw=os.pread(fd,POLL_BYTES-len(attempt['anchor'])-len(attempt['tail']),attempt['offset'])
                cursor=0;lines=0;nodes=[POLL_NODES]
                while lines<POLL_LINES:
                    end=raw.find(b'\n',cursor)
                    if end<0:break
                    line=raw[cursor:end+1];event=parse_line(line,node_budget=nodes)
                    if event['type']=='thread.started' and attempt['runtime_ack'] is None:
                        runtime=attempt['runtime']
                        ready=self._sandbox_ready(attempt['source'])
                        if not runtime['release_entered'] or ready is None:
                            raise Conflict('native original source before release')
                        self._check_pidfd(attempt,live=True)
                        if identity(attempt['producer'].pid)!=attempt['producer_identity']:
                            raise Conflict('native original producer identity changed')
                        info=os.stat('/proc/'+str(attempt['producer'].pid)+'/exe')
                        if (info.st_dev,info.st_ino)!=attempt['binary']['stamp'][:2]:
                            raise Conflict('stdout event producer not original native ELF')
                        attempt['runtime_ack']=_RuntimeStartedObservation(source,canonical({'source_id':source.id,
                            'event':event,'producer':attempt['producer_identity'],'offset':attempt['offset']+cursor,
                            'line_sha256':hashlib.sha256(line).hexdigest(),'lease_sha256':hashlib.sha256(runtime['lease'].raw).hexdigest(),
                            'sandbox_receipt_sha256':digest(json.loads(ready.raw))}))
                    cursor=end+1;lines+=1
                attempt['hash'].update(raw[:cursor]);attempt['offset']+=cursor
                attempt['anchor']=os.pread(fd,min(256,attempt['offset']),max(0,attempt['offset']-256))
                attempt['tail']=raw[cursor:];attempt['seen']=stamp
                if attempt['producer'] is not None and attempt['producer'].poll() is not None:
                    attempt['status']='EXIT_OBSERVED'
            except Exception:
                attempt['status']='QUARANTINED';raise
            return self._observation(attempt)

    def seal(self,source):return self.poll(source)

    def _observation(self,attempt):
        # Never feed diagnostic/rejected CLI output into a model usage settler.
        value=super()._observation(attempt)
        return value

    def _cleanup_attempt(self,attempt):
        errors=[]
        if attempt.get('held') is not None:attempt['held'].set()
        if attempt.get('receiver_stop') is not None:attempt['receiver_stop'].set()
        lock=attempt.get('receiver_lock')
        if lock is not None:
            with lock:
                row=attempt.get('accepted')
                if row is not None:
                    connection,original=row
                    try:
                        if original is None:raise Conflict('original receiver connection identity UNKNOWN')
                        if connection.fileno()>=0:
                            info=os.fstat(connection.fileno())
                            if (info.st_dev,info.st_ino)!=original:raise Conflict('original receiver connection FD reused')
                            try:connection.shutdown(socket.SHUT_RDWR)
                            except OSError:pass  # Close still independently attempted.
                            connection.close()
                    except BaseException as error:errors.append(error)
        try:super()._cleanup_attempt(attempt)
        except BaseException as error:errors.append(error)
        server=attempt.get('server');thread=attempt.get('server_thread')
        if server is None and attempt.get('receiver_creation_entered') and not attempt.get('listener_closed'):
            errors.append(Conflict('original receiver construction outcome UNKNOWN'))
        if server is not None:
            try:
                # Never call BaseServer.shutdown: it can wait forever when
                # original Thread.start failed before serve_forever existed.
                if server.socket.fileno()>=0:
                    info=os.fstat(server.socket.fileno())
                    if (info.st_dev,info.st_ino)!=attempt.get('listener_identity'):
                        raise Conflict('original receiver listener FD reused')
                server.server_close()
                if thread is not None and thread.ident is not None:
                    thread.join(2)
                    if thread.is_alive():raise Conflict('native original receiver cleanup incomplete')
                attempt['server']=None
                attempt['listener_closed']=True
            except BaseException as error:errors.append(error)
        if errors:
            attempt['status']='UNKNOWN';raise errors[0]
