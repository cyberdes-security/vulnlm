"""Allowlisted model gateway between the lab app and Ollama.

The app is exploitable on purpose (SSRF/RCE), so it must not hold Ollama's whole unauthenticated
API (delete, push, create). This process exposes only chat completions and downloads for catalogue
models. Standard library only: Compose runs it from a read-only mount, like internal_service.py.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_BODY=4*1024*1024  # Image chat sends data URLs up to the 2 MiB ingress cap.


def canonical(name):
    return name if ':' in name else name+':latest'


def upstream_error(exc):
    """Ollama reports failures as {"error": ...}; keep that text instead of a bare status line."""
    if isinstance(exc,urllib.error.HTTPError):
        try:return json.loads(exc.read()).get('error') or f'HTTP {exc.code}'
        except (ValueError,OSError,AttributeError):return f'HTTP {exc.code}'
    if isinstance(exc,urllib.error.URLError):return f'Ollama unreachable: {exc.reason}'
    return str(exc) or type(exc).__name__


class Gateway:
    def __init__(self, upstream, catalogue_path, extra_models=(), chat_timeout=600):
        self.upstream=upstream.rstrip('/')
        self.chat_timeout=chat_timeout
        entries=json.loads(Path(catalogue_path).read_text())['models']
        # Operator-configured models (LLM_MODEL, VISION_MODEL) are allowed and downloadable too.
        self.pullable={canonical(m['id']):m.get('pullable',True) for m in entries}
        for name in extra_models:
            if name:self.pullable.setdefault(canonical(name),True)
        self.lock=threading.Lock()
        self.jobs={}

    def allowed(self, name):
        return isinstance(name,str) and canonical(name) in self.pullable

    def installed(self):
        with urllib.request.urlopen(self.upstream+'/api/tags',timeout=5) as response:
            return {canonical(m['name']):m for m in json.load(response)['models']}

    def status(self):
        try:
            installed=self.installed();reachable=True;error=None
        except (OSError,ValueError,KeyError,TypeError) as exc:
            installed={};reachable=False;error=upstream_error(exc)
        with self.lock:
            jobs={name:self.public(job) for name,job in self.jobs.items()}
        models={name:{'installed':name in installed if reachable else None,
                      'size':installed[name].get('size') if name in installed else None,
                      'pullable':pullable,'download':jobs.get(name)} for name,pullable in self.pullable.items()}
        return {'upstream_host':urlsplit(self.upstream).hostname,'reachable':reachable,'error':error,'models':models}

    @staticmethod
    def public(job):
        return {key:job[key] for key in ('status','phase','completed','total','error','started','finished')}

    def pull(self, name):
        """Start a download. One download runs at a time; a new model replaces the running one."""
        name=canonical(name)
        with self.lock:
            running=[job for job in self.jobs.values() if job['status']=='downloading']
            for job in running:
                if job['model']==name:return self.public(job)
            for job in running:
                job.update(cancel=True,status='cancelled',finished=time.time())
            job={'model':name,'status':'downloading','phase':'starting','completed':0,'total':0,'error':None,
                 'started':time.time(),'finished':None,'layers':{},'cancel':False}
            self.jobs[name]=job
        threading.Thread(target=self.run_pull,args=(job,),daemon=True).start()
        return self.public(job)

    def cancel(self, name=None):
        with self.lock:
            for job in self.jobs.values():
                if job['status']=='downloading' and (name is None or job['model']==canonical(name)):
                    job.update(cancel=True,status='cancelled',finished=time.time())

    def run_pull(self, job):
        request=urllib.request.Request(self.upstream+'/api/pull',method='POST',headers={'Content-Type':'application/json'},
                                       data=json.dumps({'model':job['model'],'name':job['model'],'stream':True}).encode())
        try:
            with urllib.request.urlopen(request,timeout=120) as response:
                for line in response:
                    if job['cancel']:return  # Closing the stream stops Ollama; partial blobs resume later.
                    if not line.strip():continue
                    event=json.loads(line)
                    if event.get('error'):raise RuntimeError(event['error'])
                    self.progress(job,event)
                    if event.get('status')=='success':return
            raise RuntimeError('Ollama closed the download stream before it finished')
        except Exception as exc:  # Any failure is reported through the job, never raised in a thread.
            with self.lock:
                if not job['cancel']:job.update(status='error',error=upstream_error(exc),finished=time.time())

    def progress(self, job, event):
        status=str(event.get('status',''))
        with self.lock:
            if job['cancel']:return
            if event.get('digest') and event.get('total'):
                job['layers'][event['digest']]=(int(event.get('completed') or 0),int(event['total']))
                job['phase']='downloading'
            elif status=='success':
                job.update(status='done',phase='done',finished=time.time())
                job['layers']={digest:(total,total) for digest,(_,total) in job['layers'].items()}
            elif status:
                job['phase']={'pulling manifest':'manifest','verifying sha256 digest':'verifying',
                              'writing manifest':'writing'}.get(status,job['phase'])
            if job['layers']:
                job['completed']=sum(done for done,_ in job['layers'].values())
                job['total']=sum(total for _,total in job['layers'].values())

    def chat(self, body):
        request=urllib.request.Request(self.upstream+'/v1/chat/completions',data=body,method='POST',
                                       headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=self.chat_timeout) as response:
                return response.status,response.read()
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read()


def handler_for(gateway):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload, raw=False):
            body=payload if raw else json.dumps(payload).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

        def body(self):
            try:length=int(self.headers.get('Content-Length',''))
            except ValueError:length=-1
            if not 0<=length<=MAX_BODY:
                self.reply(413,{'error':'Send a JSON body of at most 4 MiB with Content-Length'});return None
            raw=self.rfile.read(length)
            try:data=json.loads(raw)
            except ValueError:data=None
            if not isinstance(data,dict):
                self.reply(400,{'error':'Send a JSON object'});return None
            return raw,data

        def do_GET(self):
            if self.path=='/health':return self.reply(200,{'status':'ok'})
            if self.path=='/models':return self.reply(200,gateway.status())
            self.reply(404,{'error':'Not found'})

        def do_POST(self):
            if self.path not in {'/v1/chat/completions','/models/pull','/models/cancel'}:
                return self.reply(404,{'error':'Not found'})
            parsed=self.body()
            if parsed is None:return
            raw,data=parsed
            model=data.get('model')
            if self.path=='/models/cancel':
                if model is not None and not gateway.allowed(model):return self.reply(403,{'error':'Model is not in the lab catalogue'})
                gateway.cancel(model);return self.reply(200,{'status':'cancelled'})
            if not gateway.allowed(model):return self.reply(403,{'error':'Model is not in the lab catalogue'})
            if self.path=='/models/pull':
                if not gateway.pullable[canonical(model)]:
                    return self.reply(422,{'error':'This local model is not in the public registry and cannot be downloaded'})
                return self.reply(202,gateway.pull(model))
            try:
                status,payload=gateway.chat(raw)
            except (OSError,ValueError) as exc:
                return self.reply(502,{'error':upstream_error(exc)})
            self.reply(status,payload,raw=True)

        def log_message(self,*args):pass
    return Handler


def serve(gateway, host='0.0.0.0', port=8080):
    return ThreadingHTTPServer((host,port),handler_for(gateway))


if __name__=='__main__':
    gateway=Gateway(os.environ.get('OLLAMA_URL','http://ollama:11434'),
                    os.environ.get('MODEL_CATALOG',Path(__file__).with_name('model_catalog.json')),
                    (os.environ.get('LLM_MODEL',''),os.environ.get('VISION_MODEL','')),
                    float(os.environ.get('CHAT_TIMEOUT','600')))
    serve(gateway,port=int(os.environ.get('PORT','8080'))).serve_forever()
