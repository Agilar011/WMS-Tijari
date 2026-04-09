import { browser } from '@web/core/browser/browser';
import { reactive, useState } from '@odoo/owl';
import { session } from '@web/session';
import { user } from '@web/core/user';

export const LUID = () => {
    return `${session.server_version_info.slice(-1)[0] === 'e' ? 'ocoo' : 'udoo'}_${odoo.info.db}_${user.login}`
};

// Memorized store
const jsonStore = (obj, key) => {
    browser.localStorage.setItem(key, JSON.stringify(obj));
};
const lstore = reactive({}, () => jsonStore(lstore, LUID()));
export function useUdooLocalStore(initialst = {}) {
    Object.assign(lstore, JSON.parse(browser.localStorage.getItem(LUID())) || initialst);
    jsonStore(lstore, LUID());
    return useState(lstore);
}

// Global store (non-memorized)
export const ustore = reactive({ recents: [] });
export function useUdooStore() {
    return useState(ustore);
}