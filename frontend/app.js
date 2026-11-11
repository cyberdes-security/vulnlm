// Application entry point: session lifecycle and chat interactions.
import { $ } from './js/dom.js';
import { I18N, t, lang, setLanguage } from './js/i18n.js';
import { renderDocuments } from './js/documents.js';
import { api, configureApi } from './js/api.js';
import { renderScenarios, setScenarios, onConfigureScenario } from './js/scenarios.js';
import { labPolicy, loadSettings, renderSettings, resetSettings, configureSettings, openSettings } from './js/settings.js';
import { modelState, loadModels, renderModels, renderModelStatus, resetModels, configureModels } from './js/models.js';

let conversationId = null;
let busy = false;
let calls = 0;
let hasTrace = false;
export let currentUser = null;
let pendingFile = null;

configureModels({getCurrentUser:()=>currentUser, log, addMessage});
configureApi({getCurrentUser:()=>currentUser, onUnauthorized:()=>{
    if (!currentUser) return;
    signedOut();
    const message=t('session_ended');
    $('login-notice').textContent=message; $('login-notice').hidden=false;
    log(message);
}});
configureSettings({log, signedOut});
onConfigureScenario(openSettings);

function applyLang(next) {
    if (!I18N[next]) next = 'en-GB';
    setLanguage(next);
    document.documentElement.lang = next;
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    // Trusted static translations only (contain <br>/<small>); never user input.
    document.querySelectorAll('[data-i18n-html]').forEach(el => { el.innerHTML = t(el.dataset.i18nHtml); });
    document.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    document.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
    document.querySelectorAll('.lang-btn').forEach(b => b.classList.toggle('active', b.dataset.lang === next));
    if (!hasTrace) $('trace-output').textContent = t('no_tx');
    renderStatus();
    renderScenarios();
    if (labPolicy) renderSettings();
    if ($('documents-dialog').open) renderDocuments();
    if (modelState) {renderModelStatus(); renderModels();}
}

export function log(text) {
    const row=document.createElement('div'); row.className='log-entry info';
    const time=document.createElement('span'); time.className='log-time';
    time.textContent=new Date().toLocaleTimeString(lang,{hour12:false});
    const message=document.createElement('span'); message.textContent=text;
    row.append(time,message); $('log-container').prepend(row);
}
export function addMessage(text, type, renderHtml=false) {
    const row=document.createElement('div'); row.className=`message ${type}`;
    const bubble=document.createElement('div'); bubble.className='bubble';
    if (type==='ai' && renderHtml) {
        // INTENTIONAL LLM10:2026 output handling vulnerability.
        // Only model output is rendered unsafely; UI labels and user input use textContent.
        bubble.innerHTML=text;
    } else bubble.textContent=text;
    row.append(bubble); $('chat-history').append(row);
    $('chat-history').scrollTop=$('chat-history').scrollHeight;
}
function renderStatus() {
    $('account-avatar').textContent=currentUser ? currentUser.name.charAt(0).toUpperCase() : '?';
    $('account-avatar').classList.toggle('admin', currentUser?.role==='admin');
    if (currentUser) $('account-status').textContent=`${currentUser.name} · ${currentUser.role} · ${currentUser.balance} ${t('credits')}`;
    else $('account-status').textContent=t('login_sub');
}
async function refreshUser() {
    try { currentUser=await api('/me',undefined,'GET'); }
    catch(error) { if (error.status===401) currentUser=null; }
    renderStatus();
}
function showApp() {
    $('advanced-settings-btn').hidden=false;
    $('login-view').hidden=true; $('app-view').hidden=false;
    if ($('chat-history').children.length===0) addMessage(t('intro'),'system-message');
}
function showLogin() {
    $('advanced-settings-btn').hidden=true;
    for (const id of ['reset-dialog','models-dialog','documents-dialog']) if ($(id).open) $(id).close();
    if ($('settings-dialog').open) $('settings-dialog').close();
    $('app-view').hidden=true; $('login-view').hidden=false;
    $('login-email').focus();
}

$('lang-switch').addEventListener('click', event => {
    const btn=event.target.closest('.lang-btn'); if (btn) applyLang(btn.dataset.lang);
});
$('login-form').addEventListener('submit', async event => {
    event.preventDefault();
    const email=$('login-email').value.trim(), password=$('login-password').value;
    const err=$('login-error');
    $('login-notice').hidden=true;
    try {
        await api('/auth/login',{email,password});
        conversationId=null; await refreshUser(); await loadSettings();
        err.hidden=true; showApp(); loadModels().catch(()=>{});
        log(t('logged_in', currentUser ? currentUser.name : email));
    } catch (ex) { err.textContent=ex.message || t('login_failed'); err.hidden=false; }
});
document.querySelectorAll('.account-chip').forEach(chip => chip.addEventListener('click', () => {
    // Teaching convenience: fills the documented synthetic credentials; the user still submits.
    $('login-email').value=chip.dataset.email; $('login-password').value=chip.dataset.password;
    $('login-submit').focus();
}));
export function signedOut() {
    currentUser=null; resetSettings(); resetModels(); $('approval-actions').replaceChildren(); conversationId=null; calls=0; $('call-counter').textContent='0';
    $('chat-history').replaceChildren();
    hasTrace=false; $('trace-output').textContent=t('no_tx');
    $('login-password').value='';
    renderStatus(); showLogin();
}
$('logout-btn').addEventListener('click', async () => {
    try { await api('/auth/logout',{}); } catch {}
    signedOut();
});

$('attach-btn').addEventListener('click', () => $('doc-file').click());
$('doc-file').addEventListener('change', () => {
    pendingFile=$('doc-file').files[0] || null;
    if (pendingFile) { $('attach-name').textContent=pendingFile.name; $('attach-chip').hidden=false; }
    else $('attach-chip').hidden=true;
});
$('attach-clear').addEventListener('click', () => {
    pendingFile=null; $('doc-file').value=''; $('attach-chip').hidden=true;
});
async function uploadPending() {
    const file=pendingFile;
    if (file.type==='application/pdf' || /\.pdf$/i.test(file.name)) throw new Error(t('pdf_unsupported'));
    const content=await file.text();
    // Lab ingress caps the body at 2 MiB; JSON-escaping binary bytes inflates size, so guard early.
    if (content.length>1500000) throw new Error(t('doc_too_large'));
    // INTENTIONAL: content is indexed into the shared RAG store; owner is the current session user.
    const body={title:file.name, content, source:'uploaded'};
    if (currentUser) body.user_id=currentUser.id;
    const data=await api('/upload_doc',body);
    hasTrace=true;
    $('trace-output').textContent=JSON.stringify({uploaded_doc:data,title:file.name,source:'uploaded',owner_id:body.user_id},null,2);
    addMessage(t('upload_ok_chat', file.name, data.id),'system-message');
    log(t('upload_ok', data.id, file.name));
    pendingFile=null; $('doc-file').value=''; $('attach-chip').hidden=true;
}

async function sendMessage() {
    const message=$('user-input').value.trim();
    if ((!message && !pendingFile) || busy) return;
    busy=true; $('send-btn').disabled=true;
    try {
        let imageData=null, imageName=null;
        if (pendingFile && ['image/png','image/jpeg'].includes(pendingFile.type)) {
            if (pendingFile.size>1000000) throw new Error(t('image_limit'));
            imageName=pendingFile.name;
            imageData=await new Promise((resolve,reject)=>{
                const reader=new FileReader();
                reader.onload=()=>resolve(reader.result); reader.onerror=()=>reject(reader.error);
                reader.readAsDataURL(pendingFile);
            });
        } else if (pendingFile) await uploadPending();
        if (message || imageData) {
            const prompt=message || t('image_prompt');
            addMessage(prompt,'user');
            if (imageData) addMessage(t('image_attached',imageName),'system-message');
            const body={message:prompt,conversation_id:conversationId,pii_filter:$('pii-toggle').checked};
            if (imageData) body.image_data_url=imageData;
            const data=await api(imageData ? '/chat/image' : '/chat',body);
            $('user-input').value='';
            if (imageData) {pendingFile=null; $('doc-file').value=''; $('attach-chip').hidden=true;}
            conversationId=data.conversation_id;
            addMessage(data.response || t('no_text_response'),'ai',data.render_html===true);
            renderApprovals(data.tools);
            calls+=data.llm_calls; $('call-counter').textContent=String(calls);
            hasTrace=true;
            const evidence={conversation_id:conversationId,tools:data.tools,retrieved_docs:data.retrieved_docs,usage:data.usage,circuit_breaker:data.circuit_breaker};
            if (data.reasoning?.length) evidence.reasoning=data.reasoning;
            $('trace-output').textContent=JSON.stringify(evidence,null,2);
            log(t('calls_tools', data.llm_calls, data.tool_executions ?? data.tools.filter(item=>item.executed!==false).length));
        }
        await refreshUser();
    } catch(error) { if(error.status!==401) {addMessage(error.message,'system-message'); log(error.message);} }
    finally {busy=false; $('send-btn').disabled=false;}
}
$('send-btn').addEventListener('click',sendMessage);
$('user-input').addEventListener('keydown',event=>{
    if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage();}
});
$('reset-btn').addEventListener('click',()=>{
    conversationId=null; $('chat-history').replaceChildren();
    addMessage(t('new_chat_msg'),'system-message');
});

// A spawn_agent result nests the sub-agent's own trace; its approval proposals belong to the same user.
function proposals(trace) {
    const found=[];
    for (const item of trace || []) {
        if (item.result?.approval_required) found.push(item.result);
        found.push(...proposals(item.result?.trace));
    }
    return found;
}

function renderApprovals(trace) {
    const list=$('approval-actions');list.replaceChildren();
    const seen=new Set();
    for (const proposal of proposals(trace)) {
        if (seen.has(proposal.approval_id)) continue;
        seen.add(proposal.approval_id);
        const card=document.createElement('section');card.className='approval-card';
        const title=document.createElement('strong');title.textContent=t('approval_required');
        const detail=document.createElement('pre');detail.textContent=JSON.stringify({tool:proposal.tool,arguments:proposal.arguments},null,2);
        const button=document.createElement('button');button.type='button';button.className='primary';button.textContent=t('approve_action');
        const status=document.createElement('p');status.className='caption';status.setAttribute('role','status');
        button.addEventListener('click',async()=>{button.disabled=true;try {
            const result=await api('/tools/approvals/'+proposal.approval_id+'/approve',{});
            detail.textContent=JSON.stringify(result,null,2);status.textContent=t('action_executed');button.remove();await refreshUser();log(t('action_executed'));
        }catch(error){status.textContent=error.message;button.disabled=false;}});
        card.append(title,detail,button,status);list.append(card);
    }
}

(async function init() {
    applyLang(lang);
    api('/lab/scenarios',undefined,'GET').then(items=>{ setScenarios(items); }).catch(error=>log(error.message));
    await refreshUser();
    if (currentUser) {await loadSettings();showApp();loadModels().catch(()=>{});} else showLogin();
})().catch(error=>{if(error.status!==401)log(error.message);});
