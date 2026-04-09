import { _t } from '@web/core/l10n/translation';
import { user } from '@web/core/user';
import { browser } from "@web/core/browser/browser";
import { toRaw } from '@odoo/owl';

import { encodeCurrentAction } from '../action_utils';
import { BookmarkCommandItem } from './palette';


export const bookmarkCurrentView = async (params) => {
    const act = encodeCurrentAction(params);
    if (!act) return;

    if (act.view_type == 'form') {
        // Remove immutable attribute
        delete act.view_mode;
        delete act.views;
    }
    if (!act._g) {
        switch (act.view_type) {
            case 'form':
                delete act.type;
                act._g = 'doc';
                break;
            case 'list':
            case 'kanban':
            case 'hierarchy':
            case 'map':
                delete act.type;
                act._g = 'dir';
                break;
            case 'pivot':
            case 'graph':
            case 'cohort':
                delete act.type;
                act._g = 'rpg';
                break;
            case 'calendar':
            case 'activity':
            case 'gantt':
            case 'grid':
                delete act.type;
                act._g = 'pln';
                break;
            default:
                if (params.isCreate)
                    act._g = 'add';
                break;
        }
    }

    const bookms = params.env.services.ui.bookmarks;
    bookms.push(act);

    await user.setUserSettings('up_bookmarks', JSON.stringify(bookms));
    params.env.services.notification.add(
        _t('Bookmark saved.'),
        {
            type: 'success',
            title: _t('Notification'),
            className: 'bookm_notify',
        }
    );
}

export const bookmarkProvider = async (env, params) => {
    const bookms = env.services.ui.bookmarks;

    const bookmarkCommands = bookms.toReversed().map((record, idx) => {
        let dname = (record._p && record.name) ? `${record._p}: ${record.name}` : record.name;
        const result = {
            Component: BookmarkCommandItem,
            _a: record._a,
            name: dname || _t('Undefined'),
            view_type: record.view_type,
            category: record._g,
            action: (flag = false) => {
                const actObj = { ...record }
                if (record.view_type == 'form') {
                    Object.assign(actObj, {
                        view_mode: 'form',
                        views: [[false, 'form']],
                    })
                }
                actObj.type = actObj.type || 'ir.actions.act_window';

                if (flag === false) {
                    env.services.action.doAction(actObj);
                } else if (flag == 0) {
                    env.services.menu.setCurrentMenu(record._a);
                    env.services.action.doAction(actObj, { clearBreadcrumbs: true });
                } else if (flag == 1) {
                    const popObj = { ...actObj, target: 'new' };
                    if (popObj.views) {
                        popObj.views = actObj.views.filter(o => ['search', popObj.view_type].includes(o[1]));
                    }
                    env.services.action.doAction(popObj);
                }
            },
            copy: () => {
                browser.navigator.clipboard.writeText(JSON.stringify(record, null, 2));
            },
            delete: async () => {
                bookms.splice(bookms.length - idx - 1, 1);
                await syncBookmark(env, bookms);
            },
        };
        if (record.view_type == 'form') {
            result.href = `/odoo/${record.res_model}/${record.res_id}`;
        }
        return result;
    });

    const recentCommands = toRaw(params.recents).toReversed().map((record, idx) => {
        return {
            Component: BookmarkCommandItem,
            name: `${record._p ? (record._p + ': ') : ''}${record.name}`,
            href: `/odoo/${record.res_model}/${record.res_id}`,
            view_type: 'form',
            category: 'rcs',
            action: (flag = false) => {
                const actObj = {
                    type: 'ir.actions.act_window',
                    view_mode: 'form',
                    views: [[false, 'form']],
                    ...record,
                }
                if (flag == 1) {
                    actObj.target = 'new';
                }
                env.services.action.doAction(actObj);
            },
            copy: () => {
                browser.navigator.clipboard.writeText(JSON.stringify(record, null, 2));
            },
            delete: async () => {
                params.recents.splice(params.recents.length - idx - 1, 1);
                env.bus.trigger('BMK:SEARCH', '');
            },
        }
    });

    return bookmarkCommands.concat(recentCommands);
};

async function syncBookmark(env, bookms) {
    await user.setUserSettings('up_bookmarks', JSON.stringify(bookms));
    env.bus.trigger('BMK:SEARCH', '');
}

export const bookmarkPalette = {
    configByNamespace: {
        default: {
            categories: ['add', 'act', 'dir', 'doc', 'pln', 'rpg', 'rcs', 'cmd'],
            categoryNames: {
                'act': _t('Quick Access'),
                'add': _t('Quick Create'),
                'dir': _t('Directory'),
                'doc': _t('Document'),
                'pln': _t('Planning'),
                'rpg': _t('Reporting'),
                'rcs': _t('Recents'),
            },
        },
    },
}
