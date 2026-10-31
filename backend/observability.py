"""Operational telemetry, kept separate from intentionally vulnerable experiment audit.

Never log request bodies, query strings, cookies, tokens, model prompts or exception
messages. Metrics use route templates, so attacker-controlled paths cannot add labels.
Counters are per process and reset on restart; scrape each worker separately.
"""
import json
import logging
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from starlette.responses import JSONResponse

request_id = ContextVar('operation_request_id', default=None)
logger = logging.getLogger('vulnlm.operations')
FIELDS = ('event', 'request_id', 'method', 'route', 'status', 'duration_ms',
          'error_type', 'revision', 'component')


class JSONFormatter(logging.Formatter):
    def format(self, record):
        value = {'timestamp':datetime.now(timezone.utc).isoformat(), 'level':record.levelname}
        value.update({name:getattr(record, name) for name in FIELDS if hasattr(record, name)})
        value.setdefault('event', record.getMessage())
        if request_id.get():
            value.setdefault('request_id', request_id.get())
        return json.dumps(value, ensure_ascii=False)


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = defaultdict(int)
        self.durations = defaultdict(float)
        self.started = time.monotonic()

    def record(self, method, route, status, seconds):
        with self.lock:
            self.requests[method, route, status] += 1
            self.durations[method, route] += seconds

    def render(self):
        def label(value):
            return json.dumps(str(value), ensure_ascii=True)
        lines = ['# HELP vulnlm_http_requests_total HTTP responses by route and status.',
                 '# TYPE vulnlm_http_requests_total counter']
        with self.lock:
            for (method, route, status), count in sorted(self.requests.items()):
                lines.append(f'vulnlm_http_requests_total{{method={label(method)},route={label(route)},status={label(status)}}} {count}')
            lines.extend(['# HELP vulnlm_http_request_duration_seconds Total request duration.',
                          '# TYPE vulnlm_http_request_duration_seconds summary'])
            for (method, route), duration in sorted(self.durations.items()):
                labels=f'method={label(method)},route={label(route)}'
                count=sum(n for (m,r,s),n in self.requests.items() if (m,r)==(method,route))
                lines.append(f'vulnlm_http_request_duration_seconds_sum{{{labels}}} {duration:.6f}')
                lines.append(f'vulnlm_http_request_duration_seconds_count{{{labels}}} {count}')
            lines.extend(['# TYPE vulnlm_process_uptime_seconds gauge',
                          f'vulnlm_process_uptime_seconds {time.monotonic()-self.started:.3f}'])
        return '\n'.join(lines)+'\n'


metrics = Metrics()


class OperationalMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        ident = uuid.uuid4().hex
        token = request_id.set(ident)
        start = time.monotonic()
        status = 500
        started = False
        method = scope['method'] if scope['method'] in {'GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS'} else 'OTHER'

        async def send_response(message):
            nonlocal status, started
            if message['type'] == 'http.response.start':
                status = message['status']
                started = True
                message = {**message, 'headers':[*message.get('headers', []), (b'x-request-id', ident.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as exc:
            logger.error('request_error', extra={'event':'request_error', 'error_type':type(exc).__name__})
            if started:
                raise
            await JSONResponse({'detail':'Internal server error', 'request_id':ident}, status_code=500)(scope, receive, send_response)
        finally:
            duration = time.monotonic()-start
            route = getattr(scope.get('route'), 'path', 'unmatched')
            metrics.record(method, route, status, duration)
            logger.log(logging.ERROR if status >= 500 else logging.INFO, 'http_request',
                       extra={'event':'http_request', 'method':method, 'route':route,
                              'status':status, 'duration_ms':round(duration*1000, 2)})
            request_id.reset(token)
