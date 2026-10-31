import { t } from './i18n.js';

const ui = {};
export function configureApi(callbacks) { Object.assign(ui, callbacks); }

export class ApiError extends Error {
    constructor(message, status) { super(message); this.name='ApiError'; this.status=status; }
}

export async function api(path, body, method='POST') {
    const session=ui.getCurrentUser?.();
    const response = await fetch(path, {method, credentials:'same-origin', cache:'no-store',
        headers: body === undefined ? {} : {'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},
        body: body === undefined ? undefined : JSON.stringify(body)});
    // Only invalidate the session that made this request, never a later login.
    if (response.status===401 && path!=='/auth/login' && session && session===ui.getCurrentUser?.()) {
        ui.onUnauthorized?.();
    }
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : {}; }
    catch { throw new ApiError(response.status===413 ? t('doc_too_large') : `HTTP ${response.status}: unexpected non-JSON response`, response.status); }
    if (!response.ok) throw new ApiError(typeof data.detail==='string' ? data.detail : JSON.stringify(data.detail), response.status);
    return data;
}
