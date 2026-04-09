import { _t } from '@web/core/l10n/translation';
import { router } from '@web/core/browser/router';

export const VIEW_IMAP = {
    form: 'ri-news-line',
    list: 'ri-list-view',
    pivot: 'ri-timeline-view',
    kanban: 'ri-kanban-view-2',
    graph: 'ri-bar-chart-box-line',
    calendar: 'ri-calendar-event-line',
    activity: 'ri-calendar-schedule-line',
    hierarchy: 'ri-organization-chart',
    gantt: 'ri-slideshow-view',
    grid: 'ri-gallery-view',
    map: 'ri-map-2-line',
    cohort: 'ri-increase-decrease-line',
};

export function encodeRecordUrl(rec, act) {
    let url = `web#id=${rec.resId}&model=${rec.resModel || act.res_model}&view_type=form`;
    if (act.id) url += `&action=${act.id}`;
    if (act.context?.active_id) url += `&active_id=${act.context.active_id}`;
    return { type: 'ir.actions.act_url', url };
}

function findContextNode(actionStack, active_id) {
    for (let i = actionStack.length - 2; i >= 0; i--) {
        const node = actionStack[i];
        if (node.resId && node.resId == active_id) return node;
    }
    return null;
}

export function encodeCurrentAction(params, hash = true) {
    const { currentApp, env } = params;
    const controller = env.services.action.currentController;
    const currentAction = controller.action;

    if (!currentApp || !currentAction || currentAction.tag == 'invalid_action') return false;

    const actionStack = controller.state.actionStack;
    if (!actionStack.length) return false;

    const target = actionStack[actionStack.length - 1];
    const isCreate = controller.state.resId == 'new';
    const isForm = target.view_type == 'form';

    let bookmarkName = target.displayName;

    if (isForm && target.resId && controller.state.resId) {
        const prevNode = actionStack[actionStack.length - 2];
        if (isCreate) {
            if (['/'].includes(bookmarkName)) {
                bookmarkName = 'New';
            }
            if (prevNode && ['list', 'kanban'].includes(prevNode.view_type)) {
                bookmarkName = `${prevNode.displayName} / New`;
            } else if (currentAction.name) {
                bookmarkName = `${currentAction.name} / New`;
            }
        } else {
            if (prevNode && ['list', 'kanban'].includes(prevNode.view_type)) {
                bookmarkName = `${prevNode.displayName} / ${bookmarkName}`;
            }
        }
        if (prevNode && prevNode.active_id) {
            const contextNode = findContextNode(actionStack, target.active_id);
            if (contextNode) bookmarkName = `${contextNode.displayName} / ${bookmarkName}`;
        }
    } else if (target.active_id) {
        const contextNode = findContextNode(actionStack, target.active_id);
        if (contextNode) bookmarkName = `${contextNode.displayName} / ${bookmarkName}`;
    } else if (typeof target.action == 'string' && target.displayName) {
        bookmarkName = target.displayName;
    }

    // Special cases
    if (bookmarkName.startsWith(`${currentApp.name} / `)) {
        bookmarkName = bookmarkName.slice(currentApp.name.length + 3);
    }

    const result = {
        _a: currentApp.appID,
        name: bookmarkName,
        type: currentAction.type,
    };

    if (controller.props.context) {
        const { lang, tz, ...context } = controller.props.context;
        if (Object.keys(context).length) result.context = context;
    }

    if (currentAction.domain?.length) result.domain = currentAction.domain;

    if (currentApp.name) {
        result._p = currentApp.name;
    }
    if (isCreate) {
        result._g = 'add';
    } else {
        if (controller.props.type) result.view_type = controller.props.type;
        if (currentAction.search_view_id) result.search_view_id = currentAction.search_view_id;
    }

    if (isForm && controller.state.resId === undefined) {
        result._g = 'cmd';
    }

    if (currentAction.type == 'ir.actions.act_window') {
        const valid_views = currentAction.views.reduce((acc, view) => {
            view[1] != result.view_type ? acc.push(view) : acc.unshift(view);
            return acc;
        }, []);

        Object.assign(result, {
            res_model: controller.props.resModel,
            views: isCreate ? [[false, 'form']] : valid_views,
        });
        if (!isForm && currentAction.view_mode) {
            result.view_mode = currentAction.view_mode;
        }
        if (controller.props?.resId && !isCreate) {
            result.res_id = controller.props.resId;
            result.views = currentAction.views.filter(o => o[1] == 'form');
        }
    } else if (result.type == 'ir.actions.client') {
        const { action, actionStack, ...currentParams } = router.current;
        Object.assign(result, {
            tag: currentAction.tag,
            params: currentParams,
            ctx_aid: currentAction.context?.active_id,
        });
    } else if (result.type == 'ir.actions.report') {
        Object.assign(result, {
            report_type: currentAction.report_type,
            report_name: currentAction.report_name,
            data: currentAction.data || {},
        });
    }

    if (hash) result._x = objectHash.MD5(result);

    return result;
}