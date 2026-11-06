"""Persistent scenario policy, snapshotted once for each HTTP request."""
import contextvars
import fcntl
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from config import settings
from scenarios import SCENARIOS

# Each protected mode preserves the workflow while enforcing its documented boundary.
OFF_EFFECTS = {
    'prompt-injection': ('Chat continues with separated reference data, secret redaction, and approval for privileged model actions.', 'Sohbet; ayrılmış referans veri, sır maskeleme ve ayrıcalıklı model eylemleri için onay ile devam eder.'),
    'hidden-context': ('Private canary and synthetic SSN are excluded from the system prompt.', 'Özel canary ve sentetik SSN sistem promptundan çıkarılır.'),
    'rag-poisoning': ('Documents remain searchable and enter model context as untrusted reference data.', 'Belgeler aranabilir kalır ve model bağlamına güvenilmeyen referans veri olarak alınır.'),
    'rag-tenants': ('Retrieval is limited to the signed-in user’s documents.', 'Arama, oturum açan kullanıcının belgeleriyle sınırlanır.'),
    'memory-poisoning': ('Memory remains available; only the owner’s notes are passed as untrusted reference data.', 'Bellek kullanılabilir; yalnızca sahibinin notları güvenilmeyen referans veri olarak aktarılır.'),
    'tool-poisoning': ('Aliases use the built-in target description instead of registry text.', 'Takma araçlar registry metni yerine hedef aracın sabit açıklamasını kullanır.'),
    'tool-rug-pull': ('Tool edits invalidate approval; execution requires the approved revision.', 'Araç düzenlemesi onayı geçersiz kılar; yürütme onaylı revizyonu gerektirir.'),
    'excessive-agency': ('Privileged model actions require explicit approval; actions check account ownership and current role.', 'Ayrıcalıklı model eylemleri açık onay gerektirir; işlemlerde hesap sahipliği ve mevcut rol kontrol edilir.'),
    'unbounded-consumption': ('Each user is limited to 10 model requests per minute.', 'Her kullanıcı dakikada en fazla 10 model isteği yapabilir.'),
    'output-xss': ('Model replies are displayed as plain text.', 'Model yanıtları düz metin olarak gösterilir.'),
    'pii-leak': ('SSN patterns are masked in chat responses, evidence, and audit output.', 'SSN biçimindeki değerler sohbet yanıtlarında, kanıtlarda ve audit çıktısında maskelenir.'),
    'history-idor': ('Model history reads are filtered by the current user.', 'Model geçmişi okumaları mevcut kullanıcıya göre filtrelenir.'),
    'shell-rce': ('Shell tools run supported commands without a shell, with files confined to the public workspace.', 'Shell araçları desteklenen komutları shell kullanmadan çalıştırır; dosyalar public çalışma alanıyla sınırlıdır.'),
    'python-execution': ('Python supports a restricted subset for calculations, output, and public workspace files.', 'Python; hesaplama, çıktı ve public çalışma alanı dosyaları için kısıtlı bir alt kümeyi destekler.'),
    'sql-injection': ('User search and saved reports use parameterized queries.', 'Kullanıcı araması ve kayıtlı raporlar parametreli sorgular kullanır.'),
    'ssrf': ('HTTP works for public IP destinations and explicitly allowed public lab URLs; private destinations and redirects are rejected.', 'HTTP, genel IP hedefleri ve açıkça izin verilen public lab URL’leri için çalışır; özel hedefler ve yönlendirmeler reddedilir.'),
    'path-traversal': ('File reads must resolve inside the public directory.', 'Dosya okuma yolu public dizini içinde kalmalıdır.'),
    'mass-assignment': ('The profile endpoint rejects role changes.', 'Profil uç noktası rol değişikliklerini reddeder.'),
    'jwt-none': ('JWTs must have a valid HS256 signature.', 'JWT için geçerli bir HS256 imzası gerekir.'),
    'csrf': ('Transfer forms require a matching Origin.', 'Transfer formları eşleşen bir Origin gerektirir.'),
    'document-idor': ('Document reads enforce ownership.', 'Belge okumalarında sahiplik kontrol edilir.'),
    'ping-injection': ('Ping uses a validated host and an argument list without a shell.', 'Ping, doğrulanmış host ve shell kullanmayan argüman listesiyle çalışır.'),
    'audit-leak': ('Audit remains available with owner filtering and private context redaction.', 'Audit, sahiplik filtresi ve özel bağlam maskelemesiyle kullanılabilir.'),
    'tool-argument-override': ('Calls cannot replace approved default arguments.', 'Çağrılar onaylanmış varsayılan argümanların yerine değer koyamaz.'),
    'ownership-spoofing': ('Document and memory ownership comes from the session; uploaded sources are marked untrusted.', 'Belge ve bellek sahipliği oturumdan alınır; yüklenen kaynaklar güvenilmeyen olarak işaretlenir.'),
    'stale-jwt-role': ('JWT authorization uses the current database role.', 'JWT yetkilendirmesi veritabanındaki mevcut rolü kullanır.'),
    'session-lifecycle': ('Sessions expire after one hour; logout revokes their linked JWTs.', 'Oturumlar bir saat sonra sona erer; çıkış, bağlı JWT’leri de iptal eder.'),
    'audit-gap': ('Tool attempts are logged before execution, including failed chat operations.', 'Başarısız sohbet işlemleri dahil araç denemeleri yürütmeden önce kaydedilir.'),
    'transaction-replay': ('Transfers require an Idempotency-Key; duplicate requests reuse the committed result.', 'Transferler Idempotency-Key gerektirir; tekrar istekler kaydedilmiş sonucu kullanır.'),
    'transfer-validation': ('Transfers require a positive amount and sufficient balance.', 'Transferler pozitif tutar ve yeterli bakiye gerektirir.'),
    'memory-disclosure': ('Memory listing is filtered by the current user.', 'Bellek listesi mevcut kullanıcıya göre filtrelenir.'),
    'history-poisoning': ('Writing to another user’s conversation is rejected.', 'Başka kullanıcının konuşmasına yazma reddedilir.'),
    'chat-csrf': ('Chat forms require a matching Origin.', 'Sohbet formları eşleşen bir Origin gerektirir.'),
    'tool-result-injection': ('Tool results remain available to the model as untrusted data; privileged follow-up actions require approval.', 'Araç sonuçları modele güvenilmeyen veri olarak iletilir; sonraki ayrıcalıklı işlemler onay gerektirir.'),
    'approval-mismatch': ('Editing a payment removes approval; execution checks the approved snapshot.', 'Ödeme düzenlemesi onayı kaldırır; yürütme onaylanan kopyayı kontrol eder.'),
    'rag-rank-crowding': ('Operator-approved documents are prioritized within the tenant scope; duplicate content is removed from bounded retrieval candidates.', 'Kiracı kapsamında yönetici onaylı belgelere öncelik verilir; sınırlı arama adaylarındaki yinelenen içerikler kaldırılır.'),
    'agent-impersonation': ('Sender permissions are bound to the authenticated actor; research workers stay researchers.', 'Gönderici yetkileri oturum kimliğine bağlanır; araştırmacı ajan araştırmacı olarak kalır.'),
    'multimodal-injection': ('Image chat continues with isolated reference data, secret redaction, and approval for privileged actions.', 'Görsel sohbet; ayrılmış referans veri, sır maskeleme ve ayrıcalıklı işlem onayı ile devam eder.'),
    'model-backdoor': ('The training_marker tool is withheld from the model tool definitions and its execution is refused, so a poisoned model’s trigger produces no real effect; chat otherwise continues.', 'training_marker aracı model araç tanımlarından çıkarılır ve yürütmesi reddedilir; böylece zehirli modelin tetikleyicisi gerçek bir etki üretmez, sohbet aksi hâlde devam eder.'),
    'sql-tool': ('SQL queries run read-only against an owner-scoped snapshot without credentials or private tables.', 'SQL sorguları, kimlik bilgileri ve özel tablolar içermeyen, kullanıcı kapsamlı bir kopyada salt okunur çalışır.'),
    'debug-config': ('Configuration status remains available; sensitive values are redacted.', 'Yapılandırma durumu kullanılabilir; hassas değerler maskelenir.'),
}
EXTRA_CONTROLS = [
    {'id':'sql-tool','group':'appsec','mapping':'Lab tool','title':'Serbest SQL aracı','title_en':'Arbitrary SQL tool','surface':'/sql_tool'},
    {'id':'debug-config','group':'appsec','mapping':'Lab endpoint','title':'Debug yapılandırma sızıntısı','title_en':'Debug configuration disclosure','surface':'/debug/config'},
]
IDS = frozenset(OFF_EFFECTS)
assert IDS == {s['id'] for s in SCENARIOS} | {s['id'] for s in EXTRA_CONTROLS}
_policy = contextvars.ContextVar('scenario_policy', default=None)
_request = contextvars.ContextVar('scenario_request', default=None)
_rate_lock = threading.Lock()
_rate_calls = {}


def policy_path():
    return settings.DATA_DIR / 'private' / 'scenario-settings.json'


def read_policy():
    try:
        data = json.loads(policy_path().read_text())
        if not isinstance(data,dict) or type(data.get('revision')) is not int or data['revision'] < 0:
            raise ValueError('Invalid revision')
        flags = data['vulnerabilities']
        if not isinstance(flags, dict) or set(flags) - IDS or any(type(v) is not bool for v in flags.values()):
            raise ValueError('Invalid switches')
        return {'revision':data['revision'], 'vulnerabilities':{key:flags.get(key, False) for key in sorted(IDS)}}
    except FileNotFoundError:
        return {'revision':0, 'vulnerabilities':dict.fromkeys(sorted(IDS), True)}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise HTTPException(503, 'Scenario settings cannot be read; repair the operator configuration file') from exc


def write_policy(revision, changes):
    if not changes or set(changes) - IDS or any(type(v) is not bool for v in changes.values()):
        raise HTTPException(422, 'Use known scenario IDs and boolean values')
    directory = policy_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'scenario-settings.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_policy()
        if state['revision'] != revision:
            raise HTTPException(409, 'Settings changed in another session; reload before saving')
        state['vulnerabilities'].update(changes)
        state['revision'] += 1
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as output:
                temporary = Path(output.name)
                json.dump(state, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, policy_path())
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return state


def enabled(key):
    if key not in IDS:
        raise ValueError(f'Unknown scenario control: {key}')
    return (_policy.get() or read_policy())['vulnerabilities'][key]


def describe_policy(state):
    scenario_ids = {item['id'] for item in SCENARIOS}
    return [{**item, 'kind':'scenario' if item['id'] in scenario_ids else 'extra',
             'enabled':state['vulnerabilities'][item['id']],
             'off_effect_en':OFF_EFFECTS[item['id']][0], 'off_effect':OFF_EFFECTS[item['id']][1]}
            for item in [*SCENARIOS, *EXTRA_CONTROLS]]


def check_origin(request, required=True):
    origin = request.headers.get('origin')
    expected = str(request.base_url).rstrip('/')
    if (required and not origin) or (origin is not None and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'A same-origin request is required')


def idempotency_key():
    request = _request.get()
    value = request.headers.get('idempotency-key', '') if request else ''
    if not value.strip() or len(value) > 128:
        raise HTTPException(428, 'Provide an Idempotency-Key of at most 128 characters')
    return value


def consume_model_request(user_id):
    if enabled('unbounded-consumption'):
        return
    now = time.monotonic()
    with _rate_lock:
        recent = [stamp for stamp in _rate_calls.get(user_id, []) if now-stamp < 60]
        if len(recent) >= 10:
            raise HTTPException(429, 'Model limit reached: 10 requests per minute per user')
        _rate_calls[user_id] = [*recent, now]


def mask_pii(value):
    if isinstance(value, str):
        return re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED]', value)
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    if isinstance(value, dict):
        return {key:mask_pii(item) for key,item in value.items()}
    return value


class ScenarioPolicyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        try:
            state = read_policy()
        except HTTPException as exc:
            return await JSONResponse({'detail':exc.detail}, status_code=exc.status_code)(scope, receive, send)
        policy_token = _policy.set(state)
        request_token = _request.set(Request(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            _request.reset(request_token)
            _policy.reset(policy_token)
