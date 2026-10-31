import { $ } from './dom.js';
import { t } from './i18n.js';
import { api } from './api.js';
import { GROUP_ORDER, localised, renderScenarios, updateScenarioPolicy } from './scenarios.js';
const ui = {};
export function configureSettings(callbacks) { Object.assign(ui, callbacks); }

export let labPolicy = null;
let pendingPolicy = {};
let settingsSaving = false;
export function resetSettings() { labPolicy=null; pendingPolicy={}; }

export async function loadSettings() {
    labPolicy=await api('/lab/settings',undefined,'GET');
    pendingPolicy={...labPolicy.vulnerabilities};
    updateScenarioPolicy(labPolicy.vulnerabilities);
    renderScenarios();renderSettings();
    applyClientPolicy();
}
function applyClientPolicy() {
    const protectPii=labPolicy?.vulnerabilities['pii-leak']===false;
    if (protectPii) $('pii-toggle').checked=true;
    $('pii-toggle').disabled=protectPii;
}
function updateSettingsSummary() {
    if (!labPolicy) return;
    const changed=Object.keys(pendingPolicy).filter(id=>pendingPolicy[id]!==labPolicy.vulnerabilities[id]).length;
    const scenarios=labPolicy.controls.filter(item=>item.kind==='scenario');
    const extras=labPolicy.controls.filter(item=>item.kind==='extra');
    const enabledCount=items=>items.filter(item=>pendingPolicy[item.id]).length;
    $('settings-summary').textContent=t('settings_counts',enabledCount(scenarios),scenarios.length,enabledCount(extras),extras.length,changed);
    $('settings-save').disabled=!labPolicy.can_manage || !changed || settingsSaving;
    $('settings-save').textContent=t(settingsSaving?'saving_settings':'save_settings');
    for (const id of ['settings-all-on','settings-all-off']) $(id).disabled=!labPolicy.can_manage || settingsSaving;
    $('settings-reload').disabled=settingsSaving;
    $('documents-open').disabled=!labPolicy.can_manage || settingsSaving;
    $('reset-open').disabled=!labPolicy.can_manage || settingsSaving;
}
export function renderSettings() {
    if (!labPolicy) return;
    $('settings-access').textContent=t(labPolicy.can_manage?'settings_admin':'settings_readonly');
    const list=$('settings-controls');list.replaceChildren();
    const needle=$('settings-filter').value.trim().toLowerCase();
    const matches=labPolicy.controls.filter(item=>!needle || [item.id,item.mapping,item.surface,localised(item,'title'),localised(item,'off_effect')].join(' ').toLowerCase().includes(needle));
    if (!matches.length) {const empty=document.createElement('p');empty.className='muted';empty.textContent=t('scenario_no_match');list.append(empty);}
    for (const group of GROUP_ORDER) {
        const controls=matches.filter(item=>item.group===group);if(!controls.length) continue;
        const section=document.createElement('section');section.className='settings-group';
        const heading=document.createElement('h3');heading.textContent=t('group_'+group);section.append(heading);
        for (const item of controls) {
            const row=document.createElement('div');row.className='settings-control';row.dataset.scenarioId=item.id;
            const copy=document.createElement('div');copy.className='settings-control-copy';
            const label=document.createElement('label');label.htmlFor='setting-'+item.id;label.textContent=localised(item,'title');
            const meta=document.createElement('p');meta.className='caption';meta.textContent=item.mapping+' · '+item.surface;
            const effect=document.createElement('p');effect.className='settings-effect';effect.textContent=t('when_off')+': '+localised(item,'off_effect');
            copy.append(label,meta,effect);
            const toggle=document.createElement('div');toggle.className='settings-switch';
            const state=document.createElement('span');state.className='settings-state';state.textContent=t(pendingPolicy[item.id]?'vulnerability_on':'protection_on');
            const input=document.createElement('input');input.type='checkbox';input.role='switch';input.id='setting-'+item.id;
            input.checked=pendingPolicy[item.id];input.disabled=!labPolicy.can_manage || settingsSaving;
            input.setAttribute('aria-label',localised(item,'title'));input.setAttribute('aria-describedby','effect-'+item.id);effect.id='effect-'+item.id;
            input.addEventListener('change',()=>{pendingPolicy[item.id]=input.checked;state.textContent=t(input.checked?'vulnerability_on':'protection_on');updateSettingsSummary();});
            toggle.append(state,input);row.append(copy,toggle);section.append(row);
        }
        list.append(section);
    }
    updateSettingsSummary();
}
export async function openSettings(scenarioId='') {
    $('settings-error').hidden=true;
    $('settings-filter').value=scenarioId;
    if (!$('settings-dialog').open) $('settings-dialog').showModal();
    try {await loadSettings();} catch(error) {$('settings-error').textContent=error.message;$('settings-error').hidden=false;}
    $('settings-filter').focus();
}
$('advanced-settings-btn').addEventListener('click',()=>openSettings());
$('settings-close').addEventListener('click',()=>$('settings-dialog').close());
$('settings-filter').addEventListener('input',renderSettings);
$('settings-reload').addEventListener('click',async()=>{try {await loadSettings();$('settings-error').hidden=true;}catch(error){$('settings-error').textContent=error.message;$('settings-error').hidden=false;}});
for (const [id,value] of [['settings-all-on',true],['settings-all-off',false]]) {
    $(id).addEventListener('click',()=>{if(!labPolicy?.can_manage)return;for(const key of Object.keys(pendingPolicy))pendingPolicy[key]=value;renderSettings();});
}
$('settings-save').addEventListener('click',async()=>{
    if (!labPolicy?.can_manage || settingsSaving) return;
    const changes=Object.fromEntries(Object.entries(pendingPolicy).filter(([key,value])=>value!==labPolicy.vulnerabilities[key]));
    if (!Object.keys(changes).length) return;
    settingsSaving=true;$('settings-error').hidden=true;renderSettings();
    try {
        labPolicy=await api('/lab/settings',{revision:labPolicy.revision,vulnerabilities:changes},'PUT');
        pendingPolicy={...labPolicy.vulnerabilities};
        applyClientPolicy();
        updateScenarioPolicy(labPolicy.vulnerabilities);
        renderScenarios();ui.log(t('settings_saved'));
    } catch(error) {$('settings-error').textContent=error.message;$('settings-error').hidden=false;}
    finally {settingsSaving=false;renderSettings();}
});
$('reset-open').addEventListener('click',()=>{
    if (!labPolicy?.can_manage) return;
    $('reset-error').hidden=true; $('reset-settings').checked=true; $('reset-dialog').showModal();
});
for (const id of ['reset-close','reset-cancel']) $(id).addEventListener('click',()=>$('reset-dialog').close());
$('reset-confirm').addEventListener('click',async()=>{
    const button=$('reset-confirm'); button.disabled=true; button.textContent=t('resetting'); $('reset-error').hidden=true;
    try {
        await api('/lab/settings/reset',{include_settings:$('reset-settings').checked});
        // Every session is gone, ours included: start again from the login screen.
        $('settings-dialog').close(); ui.signedOut(); ui.log(t('reset_done'));
        $('login-notice').textContent=t('reset_done'); $('login-notice').hidden=false;
    } catch(error) {$('reset-error').textContent=error.message;$('reset-error').hidden=false;}
    finally {button.disabled=false; button.textContent=t('reset_confirm');}
});
