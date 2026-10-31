// Operator decisions about provenance are independent of upload source labels.
import { $ } from './dom.js';
import { t } from './i18n.js';
import { api } from './api.js';

let documents = [];
let saving = false;

export function renderDocuments() {
    const list = $('documents-list');
    list.replaceChildren();
    for (const doc of documents) {
        const row = document.createElement('section'); row.className='settings-control';
        const copy = document.createElement('div');
        const title = document.createElement('strong'); title.textContent=doc.title;
        const meta = document.createElement('p'); meta.className='caption';
        meta.textContent=t('document_owner', doc.id, doc.owner_id);
        const status = document.createElement('p'); status.className='caption';
        status.textContent=t(doc.trusted?'document_trusted':'document_untrusted');
        copy.append(title, meta, status);
        const button = document.createElement('button'); button.type='button'; button.className='linkbtn';
        button.textContent=t(doc.trusted?'document_revoke':'document_approve');
        button.disabled=saving;
        button.addEventListener('click', async () => {
            saving=true; renderDocuments(); $('documents-error').hidden=true;
            try {
                await api('/lab/documents/'+doc.id+'/trust', {trusted:!doc.trusted}, 'PUT');
                documents=await api('/lab/documents', undefined, 'GET');
            } catch (error) { $('documents-error').textContent=error.message; $('documents-error').hidden=false; }
            finally { saving=false; renderDocuments(); }
        });
        row.append(copy, button); list.append(row);
    }
}

async function openDocuments() {
    $('documents-error').hidden=true;
    if (!$('documents-dialog').open) $('documents-dialog').showModal();
    try { documents=await api('/lab/documents', undefined, 'GET'); renderDocuments(); }
    catch (error) { $('documents-error').textContent=error.message; $('documents-error').hidden=false; }
}
$('documents-open').addEventListener('click', openDocuments);
$('documents-close').addEventListener('click', ()=>$('documents-dialog').close());
