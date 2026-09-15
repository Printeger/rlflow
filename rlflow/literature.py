"""Question-scoped, quota-bound literature retrieval outside CPU command networking."""
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from .store import Conflict,atomic,canonical,sha

MAX_BYTES=512000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise Conflict('literature redirects are not authorized')


def arxiv(question):
    url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode({'search_query':'all:'+question,'start':0,'max_results':3})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'rlflow-literature/1'}),timeout=20) as response:
        raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise Conflict('literature response exceeds bounded retrieval')
    doc=ET.fromstring(raw);ns={'a':'http://www.w3.org/2005/Atom'}
    return {'query_url':url,'raw_sha256':__import__('hashlib').sha256(raw).hexdigest(),
            'sources':[{'title':e.findtext('a:title','',ns),'url':e.findtext('a:id','',ns),
                        'abstract':e.findtext('a:summary','',ns)} for e in doc.findall('a:entry',ns)[:3]]}


def retrieve(store,task_id,question,fetch=arxiv):
    state=store.replay();task=state['tasks'][task_id]
    package=state.get('packages',{}).get(task.get('package_id'),{})
    if package.get('spec',{}).get('scout_sources',[])!=['arxiv']:
        raise Conflict('external retrieval disabled; package has no approved source')
    if not isinstance(question,str) or not 1<=len(question)<=1000:raise Conflict('bounded research question required')
    from .research import record
    cycle=record(state,task);index=cycle['valid_cycles']
    if index not in cycle['scout_cycles']:raise Conflict('retrieval requires a dispatched question consultation')
    eid='L-'+sha({'package':package['id'],'task':task_id,'cycle':index})[:16]
    if eid in state['evidence']:return state['evidence'][eid]
    # Durable intent makes retries return a pending fact instead of silently
    # issuing repeated network requests after an unknown transport outcome.
    def reserve(s):
        c=record(s,s['tasks'][task_id]);c.setdefault('retrievals',{})[eid]={'status':'START_INTENT','question':question}
    current=record(state,task).get('retrievals',{}).get(eid)
    if current:raise Conflict('literature fetch already attempted; reconcile saved source')
    store.transact('LITERATURE_FETCH_INTENT',eid+':intent',reserve,object_id=eid,expected=state['version'])
    result=fetch(question)
    if len(canonical(result))>MAX_BYTES or len(result.get('sources',[]))>3:raise Conflict('unbounded source response')
    path=store.root/'literature'/eid;atomic(path/'result.json',canonical(result))
    evidence={'id':eid,'task_id':task_id,'package_id':package['id'],'role':'ScoutSource','scope':'EXTERNAL_SOURCE',
              'path':str(path),'sha256':sha(result),'accepted':True,'summary':'Untrusted external source material; no execution or adoption authority'}
    def finish(s):
        s['evidence'][eid]=evidence;record(s,s['tasks'][task_id])['retrievals'][eid]['status']='COLLECTED'
    store.transact('LITERATURE_COLLECTED',eid+':collect',finish,object_id=eid)
    return evidence
