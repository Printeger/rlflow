"""Installed CLI against a loopback-only synthetic Responses endpoint."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def run(destination,confined=False):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    requests=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            number=len(requests)+1;requests.append({'path':self.path,'model':body.get('model')})
            item={'id':'msg_'+str(number),'type':'message','role':'assistant','status':'completed',
                  'content':[{'type':'output_text','text':'offline fixture '+str(number),'annotations':[]}]}
            response={'id':'resp_'+str(number),'object':'response','created_at':1,'status':'completed','output':[item],
                      'usage':{'input_tokens':number*100,'output_tokens':number*10,'total_tokens':number*110,
                               'input_tokens_details':{'cached_tokens':number*20}}}
            events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}},
                    {'type':'response.output_item.added','output_index':0,'item':{**item,'status':'in_progress','content':[]}},
                    {'type':'response.output_text.delta','output_index':0,'content_index':0,'item_id':item['id'],'delta':item['content'][0]['text']},
                    {'type':'response.output_item.done','output_index':0,'item':item},
                    {'type':'response.completed','response':response}]
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for event in events:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
        def log_message(self,*args):pass
    server=http.server.HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='rlflow-offline-usage-') as temp:
            root=Path(temp);home=root/'codex';home.mkdir();(root/'tmp').mkdir()
            settings={'model_provider':'offline','model_providers.offline.name':'Offline usage fixture',
                      'model_providers.offline.base_url':f'http://127.0.0.1:{server.server_port}/v1',
                      'model_providers.offline.wire_api':'responses','model_providers.offline.requires_openai_auth':False,
                      'model_providers.offline.request_max_retries':0,'model_providers.offline.stream_max_retries':0,
                      'features.enable_request_compression':False}
            config=[]
            for k,v in settings.items():config.extend(['-c',k+'='+json.dumps(v)])
            env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'CODEX_HOME':str(home),'TMPDIR':str(root/'tmp')}
            version=subprocess.check_output(['/usr/local/bin/codex','--version'],env=env,text=True).strip()
            summaries=[];session=None
            for n in (1,2):
                argv=['/usr/local/bin/codex','exec',*config]
                if session:argv+=['resume',session]
                argv+=['--json','--skip-git-repo-check','Return a short fixture message.']
                actual=argv
                if confined:
                    wrapper='import os,sys;sys.path.insert(0,sys.argv[2]);from rlflow.resources import confine_writes;confine_writes(sys.argv[1]);os.execv(sys.argv[3],sys.argv[3:])'
                    actual=[sys.executable,'-I','-c',wrapper,str(root),str(Path(__file__).resolve().parents[1]),*argv]
                result=subprocess.run(actual,cwd=root,env=env,capture_output=True,text=True,timeout=30)
                (destination/f'{n}.stdout.jsonl').write_text(result.stdout)
                (destination/f'{n}.stderr.log').write_text(result.stderr)
                rows=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                session=next((r['thread_id'] for r in rows if r.get('type')=='thread.started'),session)
                summaries.append({'argv':argv,'exit_code':result.returncode,'usage':[r.get('usage') for r in rows if r.get('type')=='turn.completed']})
                if result.returncode or session is None:break
            report={'inherited_write_confinement':confined,'version':version,'requests':requests,'runs':summaries,'real_model_calls':0}
            (destination/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':run(sys.argv[1],len(sys.argv)>2 and sys.argv[2]=='--confined')
