import { t, lang, setLanguage } from './i18n.js';
const $=id=>document.getElementById(id);
let state=null, offline=false, pending=false, timer;
const states={ok:'setup_ok',disabled:'setup_disabled',not_ready:'setup_not_ready',unavailable:'setup_unavailable',schema_mismatch:'setup_schema_mismatch'};
function render() {
    document.documentElement.lang=lang;
    document.title='VulnLM · '+t('setup_title');
    document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n);});
    document.querySelectorAll('.lang-btn').forEach(el=>el.classList.toggle('active',el.dataset.lang===lang));
    const ready=state?.status==='ready' && !offline;
    $('setup-status').textContent=t(offline?'setup_offline':state?ready?'setup_ready':'setup_pending':'setup_wait');
    $('setup-status').classList.toggle('ready',ready);
    for(const key of ['database','rag','model']) {
        const value=offline?'unavailable':state?.checks?.[key];
        $('check-'+key).textContent=value?t(states[value]||'setup_unavailable'):'…';
        $('check-'+key).classList.toggle('ready',value==='ok');
    }
    const source={lab:'setup_lab',host:'setup_host',custom:'setup_custom',native:'setup_native'};
    $('setup-model').textContent=state?[state.active_model,t(source[state.model_source]||'setup_native')].filter(Boolean).join(' · '):'';
    $('setup-help').hidden=ready;
    $('setup-refresh').disabled=pending;
    const job=!offline && state?.download;
    $('setup-download').hidden=!job;
    if(job?.total>0) $('setup-progress').value=Math.max(0,Math.min(100,(job.completed||0)*100/job.total));
    else $('setup-progress').removeAttribute('value');
}
async function check() {
    if(pending)return;
    clearTimeout(timer); pending=true; render();
    const controller=new AbortController(); const deadline=setTimeout(()=>controller.abort(),20000);
    try {
        const response=await fetch('/setup/status',{cache:'no-store',signal:controller.signal});
        const data=await response.json();
        if(!['ready','not_ready'].includes(data.status) || !data.checks)throw new Error('Invalid setup response');
        state=data;offline=false;
    } catch {offline=true;}
    finally {
        clearTimeout(deadline);pending=false;render();
        if(offline || state?.status!=='ready')timer=setTimeout(check,5000);
    }
}
$('setup-refresh').addEventListener('click',check);
$('setup-language').addEventListener('click',event=>{
    const button=event.target.closest('[data-lang]');if(button){setLanguage(button.dataset.lang);render();}
});
window.addEventListener('pagehide',()=>clearTimeout(timer));
check();
