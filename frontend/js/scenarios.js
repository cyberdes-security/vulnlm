import { $ } from './dom.js';
import { I18N, t, lang } from './i18n.js';
let configureScenario;
export function onConfigureScenario(callback) { configureScenario = callback; }

let scenarioItems = [];
let scenarioFilter = '';
export const GROUP_ORDER = ['llm','agentic','appsec','boundary'];
// Turkish is the source language; the catalogue carries *_en fields for the English UI.
export function localised(item, field) {
    return (lang==='en-GB' && item[field+'_en']) || item[field] || '';
}
function scenarioCard(item) {
    const card=document.createElement('details'); card.className='scenario';
    const title=document.createElement('summary'); title.textContent=localised(item,'title');
    const state=document.createElement('span'); state.className='scenario-state '+(item.enabled===false?'protected':'vulnerable');
    state.title=t(item.enabled===false?'protection_on':'vulnerability_on');title.append(state);
    const body=document.createElement('div'); body.className='scenario-body';

    const meta=document.createElement('p'); meta.className='scenario-meta';
    const mapping=document.createElement('span'); mapping.className='scenario-tag'; mapping.textContent=item.mapping;
    const surface=document.createElement('code'); surface.title=t('scenario_surface'); surface.textContent=item.surface;
    meta.append(mapping,surface);

    const detail=document.createElement('p'); detail.className='scenario-detail';
    detail.textContent=localised(item,'detail');

    const evidence=document.createElement('p'); evidence.className='scenario-evidence';
    const label=document.createElement('strong'); label.textContent=t('evidence_label');
    evidence.append(label, document.createTextNode(' ' + localised(item,'evidence')));

    const configure=document.createElement('button');configure.type='button';configure.className='linkbtn scenario-configure';configure.textContent=t('configure_scenario');
    configure.addEventListener('click',()=>configureScenario(item.id));
    body.append(meta,detail,evidence,configure); card.append(title,body);
    return card;
}
function groupHeading(group, count) {
    if (!group) return null;
    const heading=document.createElement('p'); heading.className='scenario-group';
    const name=document.createElement('span'); name.textContent=I18N['en-GB']['group_'+group] ? t('group_'+group) : group;
    const total=document.createElement('span'); total.className='scenario-group-count'; total.textContent=count;
    heading.append(name,total);
    return heading;
}
export function renderScenarios() {
    const list=$('scenario-list'); if (!list) return;
    if (scenarioItems.length) $('scenario-count').textContent=String(scenarioItems.length);
    const needle=scenarioFilter.trim().toLowerCase();
    const matches=scenarioItems.filter(item => !needle ||
        [item.id, item.mapping, item.surface, localised(item,'title'), localised(item,'detail'), localised(item,'evidence')]
            .join(' ').toLowerCase().includes(needle));
    list.replaceChildren();
    if (!matches.length) {
        const empty=document.createElement('p'); empty.className='muted scenario-empty';
        empty.textContent=t('scenario_no_match'); list.append(empty); return;
    }
    // Known groups first, in catalogue order; anything unrecognised keeps its own section.
    const groups=[...GROUP_ORDER, ...new Set(matches.map(item => item.group).filter(g => !GROUP_ORDER.includes(g)))];
    for (const group of groups) {
        const items=matches.filter(item => item.group===group);
        if (!items.length) continue;
        const heading=groupHeading(group, items.length);
        if (heading) list.append(heading);
        for (const item of items) list.append(scenarioCard(item));
    }
}

export function setScenarios(items) { scenarioItems = items; renderScenarios(); }
export function updateScenarioPolicy(policy) {
    scenarioItems = scenarioItems.map(item => ({...item, enabled:policy[item.id]}));
    renderScenarios();
}
$('scenario-filter').addEventListener('input', event => {
    scenarioFilter=event.target.value; renderScenarios();
});
