import { $ } from './dom.js';
import { t } from './i18n.js';
import { api } from './api.js';
import { localised } from './scenarios.js';
const ui = {};
export function configureModels(callbacks) { Object.assign(ui, callbacks); }

export let modelState = null;
let modelPoll = null;
let modelBusy = false;
let generation = 0;
let modelRequest = null;
let pollFailure = null;
let pollFailures = 0;
export function resetModels() {
    generation++; modelState=null; modelRequest=null;
    pollFailure=null; pollFailures=0; clearTimeout(modelPoll); modelPoll=null;
}

function formatBytes(bytes) {
    return bytes ? (bytes/1e9).toFixed(1)+' GB' : '—';
}
function downloadTotal(item) {
    // Ollama reports each layer's size only when that layer starts, so the catalogue size is the floor.
    return Math.max(item?.download?.total||0, item?.size_bytes||0);
}
function downloadPercent(item) {
    const total=downloadTotal(item);
    return item?.download && total ? Math.min(100, Math.floor(item.download.completed*100/total)) : 0;
}
function modelName(id) {
    const item=modelState?.models.find(model=>model.id===id);
    return item ? `${item.name} (${item.id})` : id;
}
function isDownloading(item) {
    return item?.download?.status==='downloading';
}
function downloadTitle(item) {
    const job=item.download;
    if (!isDownloading(item)) return t('model_dl_starting', item.name);
    if (['verifying','writing'].includes(job.phase)) return t('model_dl_verifying', item.name);
    return job.total ? t('model_dl_progress', item.name, downloadPercent(item), formatBytes(job.completed), formatBytes(downloadTotal(item))) : t('model_dl_starting', item.name);
}
function scheduleModelPoll() {
    clearTimeout(modelPoll);
    if (!ui.getCurrentUser()) return;
    // Poll quickly while a download runs so progress and the switch-over show without a reload.
    const fast=modelState?.models.some(isDownloading) || modelState?.pending;
    const delay=pollFailures ? Math.min(60000, 15000 * 2 ** Math.min(pollFailures-1, 2)) : fast ? 1500 : 15000;
    modelPoll=setTimeout(()=>loadModels().catch(()=>{}), delay);
}
export function loadModels() {
    if (modelRequest?.generation===generation) return modelRequest.promise;
    const requestGeneration=generation;
    const promise=(async()=>{
        try {
            const next=await api('/lab/models',undefined,'GET');
            if (requestGeneration!==generation || !ui.getCurrentUser()) return;
            const previous=modelState;
            modelState=next;
            if (pollFailure) ui.log(t('model_status_restored'));
            pollFailure=null; pollFailures=0;
            announceModelChange(previous, modelState);
            renderModelStatus(); renderModels();
        } catch(error) {
            if (requestGeneration!==generation || !ui.getCurrentUser()) return;
            pollFailures++;
            const failure=error.status ? `http:${error.status}` : 'connection';
            if (pollFailure!==failure) {
                ui.log(error.status ? t('model_status_http_error',error.status) : t('model_status_connection_error'));
            }
            pollFailure=failure;
            renderModelStatus(); renderModels();
            throw error;
        } finally {
            if (requestGeneration===generation) {modelRequest=null; scheduleModelPoll();}
        }
    })();
    modelRequest={generation:requestGeneration,promise};
    return promise;
}
function announceModelChange(previous, next) {
    if (!previous?.pending || next.pending===previous.pending) return;
    const target=next.models.find(model=>model.id===previous.pending);
    let text;
    if (next.active===previous.pending) text=t('model_switched', modelName(next.active));
    else if (target?.download?.status==='error') text=t('model_dl_failed', modelName(previous.pending), target.download.error, modelName(next.active));
    else if (!next.pending) text=t('model_dl_cancelled', modelName(previous.pending), modelName(next.active));
    if (text) {ui.addMessage(text,'system-message'); ui.log(text);}
}
export function renderModelStatus() {
    if (pollFailure) {
        $('settings-model-note').textContent=t('model_status_unavailable');
        $('model-download').hidden=false;
        $('model-download-title').textContent=t('model_status_unavailable');
        $('model-download-note').textContent=t('model_status_connection_error');
        $('model-download-bar').hidden=true; $('model-download-cancel').hidden=true;
        return;
    }
    if (!modelState) return;
    const active=modelState.models.find(model=>model.active);
    const pending=modelState.models.find(model=>model.pending);
    $('model-chip').textContent=t('model_chip', modelState.active);
    $('model-chip').title=modelName(modelState.active);
    $('settings-model-name').textContent=modelName(modelState.active);
    let title='', note='';
    if (pending) {
        title=downloadTitle(pending);
        note=t('model_dl_until', modelName(modelState.active));
    } else if (active && active.installed===false) {
        title=isDownloading(active) ? downloadTitle(active) : t('model_missing', modelName(active.id));
        note=isDownloading(active) ? t('model_dl_active_missing', modelName(active.id)) : '';
    }
    $('settings-model-note').textContent=pending ? t('model_dl_until', modelName(modelState.active)) : '';
    $('model-download').hidden=!title;
    $('model-download-title').textContent=title;
    $('model-download-note').textContent=note;
    $('model-download-bar').hidden=!isDownloading(pending||active);
    $('model-download-bar').value=pending||active ? downloadPercent(pending||active) : 0;
    $('model-download-cancel').hidden=!(modelState.can_manage && isDownloading(pending||active));
}
function modelStatusText(item) {
    if (isDownloading(item)) return t('model_downloading', downloadPercent(item));
    if (item.installed===true) return t('model_installed');
    if (item.installed===false) return item.pullable ? t('model_not_installed', formatBytes(item.size_bytes)) : t('model_local_only');
    return t('model_unknown');
}
function modelCard(item) {
    const card=document.createElement('article');card.className='model-card';card.dataset.model=item.id;
    card.classList.toggle('active',item.active);card.classList.toggle('pending',item.pending);
    const head=document.createElement('div');head.className='model-card-head';
    const title=document.createElement('div');
    const name=document.createElement('strong');name.className='model-name';name.textContent=item.name;
    const id=document.createElement('code');id.textContent=item.id;
    title.append(name,id);
    const badges=document.createElement('div');badges.className='model-badges';
    for (const [flag,key] of [[item.default,'model_default'],[item.active,'model_active'],[item.pending,'model_pending']]) {
        if (!flag) continue;
        const badge=document.createElement('span');badge.className='model-badge '+key.replace('model_','');badge.textContent=t(key);badges.append(badge);
    }
    head.append(title,badges);
    const meta=document.createElement('p');meta.className='model-meta';
    meta.textContent=[item.family,item.parameters,item.quantization,item.context&&t('model_context',Math.round(item.context/1024)),formatBytes(item.installed_size||item.size_bytes),
        ...(item.capabilities||[]).map(cap=>t('model_cap_'+cap))].filter(Boolean).join(' · ');
    const description=document.createElement('p');description.className='model-desc';description.textContent=localised(item,'description');
    card.append(head,meta,description);
    if (item.thinking!==null && item.thinking!==undefined) card.append(thinkingControl(item));
    const foot=document.createElement('div');foot.className='model-card-foot';
    const state=document.createElement('span');
    state.className='model-status '+(isDownloading(item)?'downloading':item.installed===true?'installed':item.installed===false?'missing':'unknown');
    state.textContent=modelStatusText(item);
    foot.append(state);
    if (isDownloading(item)) {const bar=document.createElement('progress');bar.max=100;bar.value=downloadPercent(item);foot.append(bar);}
    const button=document.createElement('button');button.type='button';
    const usable=item.installed!==false || item.pullable;
    button.className=item.active||!usable ? 'secondary' : 'primary';
    button.textContent=item.active&&item.installed!==false ? t('model_in_use') : modelBusy ? t('model_working') : item.installed===false ? t('model_download_use') : t('model_use');
    button.disabled=!modelState.can_manage || modelBusy || (item.active&&item.installed!==false) || item.pending || !usable || isDownloading(item);
    button.addEventListener('click',()=>selectModel(item.id));
    foot.append(button);
    card.append(foot);
    return card;
}
function thinkingControl(item) {
    const row=document.createElement('div');row.className='model-thinking';
    const copy=document.createElement('div');
    const label=document.createElement('label');label.htmlFor='thinking-'+item.id;label.textContent=t('model_thinking');
    const note=document.createElement('p');note.className='caption';note.textContent=t(item.thinking?'model_thinking_on':'model_thinking_off');
    copy.append(label,note);
    const toggle=document.createElement('div');toggle.className='settings-switch';
    const input=document.createElement('input');input.type='checkbox';input.role='switch';input.id='thinking-'+item.id;
    input.checked=item.thinking;input.disabled=!modelState.can_manage || modelBusy;
    input.addEventListener('change',()=>setThinking(item.id,input.checked));
    toggle.append(input);row.append(copy,toggle);
    return row;
}
async function setThinking(id, enabled) {
    if (!modelState?.can_manage || modelBusy) return;
    modelBusy=true; $('models-error').hidden=true; renderModels();
    try {
        modelState=await api('/lab/models/thinking',{model:id,enabled},'PUT');
        ui.log(t('model_thinking_saved', modelName(id), t(enabled?'on':'off')));
    } catch(error) {$('models-error').textContent=error.message;$('models-error').hidden=false;}
    finally {modelBusy=false; renderModels();}
}
export function renderModels() {
    if (!modelState) return;
    $('models-access').textContent=t(modelState.can_manage?'models_admin':'models_readonly');
    const source=modelState.source;
    let text=source.kind==='host' ? t('models_source_host', source.host) : source.kind==='lab' ? t('models_source_lab') : source.host ? t('models_source_custom', source.host) : '';
    if (pollFailure) text=t('model_status_unavailable');
    else if (!modelState.gateway) text=t('models_no_gateway', modelState.gateway_error||'');
    else if (!source.reachable) text=t('models_unreachable', source.error||'');
    $('models-source').textContent=text;
    $('models-source').classList.toggle('warning', Boolean(pollFailure) || !modelState.gateway || !source.reachable);
    $('models-vision').textContent=modelState.vision ? t('models_vision', modelName(modelState.vision)) : t('models_vision_none');
    $('models-list').replaceChildren(...modelState.models.map(modelCard));
}
async function selectModel(id) {
    if (!modelState?.can_manage || modelBusy) return;
    modelBusy=true; $('models-error').hidden=true; renderModels();
    try {
        modelState=await api('/lab/models/active',{model:id},'PUT');
        const text=modelState.active===id ? t('model_selected', modelName(id)) : t('model_dl_started', modelName(id), modelName(modelState.active));
        ui.addMessage(text,'system-message'); ui.log(text);
    } catch(error) {$('models-error').textContent=error.message;$('models-error').hidden=false;}
    finally {modelBusy=false; renderModelStatus(); renderModels(); scheduleModelPoll();}
}
async function openModels() {
    $('models-error').hidden=true;
    if (!$('models-dialog').open) $('models-dialog').showModal();
    renderModels();
    try {await loadModels();} catch(error) {$('models-error').textContent=error.message;$('models-error').hidden=false;}
}
$('models-open').addEventListener('click',openModels);
$('models-close').addEventListener('click',()=>$('models-dialog').close());
$('models-reload').addEventListener('click',openModels);
$('model-download-cancel').addEventListener('click',async()=>{
    $('model-download-cancel').disabled=true;
    try {
        const previous=modelState;
        modelState=await api('/lab/models/pending',undefined,'DELETE');
        announceModelChange(previous, modelState);
        renderModelStatus(); renderModels();
    } catch(error) {ui.log(error.message);}
    finally {$('model-download-cancel').disabled=false;}
});
