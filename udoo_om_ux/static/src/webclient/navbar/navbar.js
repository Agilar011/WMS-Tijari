import { NavBar } from '@web/webclient/navbar/navbar';

import { _t } from '@web/core/l10n/translation';
import { user } from '@web/core/user';
import { browser } from '@web/core/browser/browser';
import { localization } from '@web/core/l10n/localization';
import { cookie } from '@web/core/browser/cookie';
import { isMobileOS } from '@web/core/browser/feature_detection';
import { useSortable } from '@web/core/utils/sortable_owl';
import { useCommand } from '@web/core/commands/command_hook';
import { usePopover } from '@web/core/popover/popover_hook';
import { useAutofocus, useService, useBus } from '@web/core/utils/hooks';
import { computeAppsAndMenuItems, reorderApps } from '@web/webclient/menus/menu_helpers';
import { DropdownItem } from '@web/core/dropdown/dropdown_item';
import { Component, EventBus, onWillStart, onPatched, useExternalListener, useState, useRef } from '@odoo/owl';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

import { bookmarkCurrentView, bookmarkPalette, bookmarkProvider } from '../bookm/provider';
import { BookmarkPalette } from '../bookm/palette';
import { VIEW_IMAP } from '../action_utils';

const MAX_RECENTS = 50;

export class OmuxNavBar extends NavBar {
    static template = 'udoo_om_ux.OmuxNavBar';
    static components = { ...NavBar.components, BookmarkPalette }

    setup() {
        super.setup();

        this.cmd = useService('command');
        this.pwa = useService('pwa');
        this.orm = useService('orm');
        this.ui = useService('ui');
        this.uo = useUdooStore();
        this.ue = useUdooLocalStore();

        this.isMobileOS = isMobileOS();
        this.user = user;

        this.view_imap = VIEW_IMAP;

        const menuOrder = JSON.parse(user.settings?.ps_menu_orders || 'null');
        this.menuApps = computeAppsAndMenuItems(this.menuService.getMenuAsTree('root')).apps;
        this.originApps = Array.of(...this.menuApps);

        if (menuOrder)
            reorderApps(this.menuApps, menuOrder);

        this.uo.orderedApps = this.menuApps;

        this.uState = useState({
            focusix: null,
            ui_view: this.ue.sidenav ? 'space' : 'app',
        });

        this.mapop = usePopover(MenuAppContextMenu, {
            setActiveElement: false,
            closeOnClickAway: true,
            animation: false,
        });

        this.mipop = usePopover(SideNavSub, {
            arrow: false,
            closeOnClickAway: true,
            setActiveElement: false,
            position: 'right',
            popoverClass: 'sidenav_2nd fs-6',
            onPositioned: (subNav, xPos) => {
                if (this.blockAutoSubnav) {
                    this.mipop.close();
                    return;
                }
                this.computeSubnavPos(subNav);
            },
        });

        /* Favorites sortable */
        this.favDragRoot = useRef('fav_drag_root');
        useSortable({
            ref: this.favDragRoot,
            elements: '.u_draggable',
            applyChangeOnDrop: true,
            cursor: 'move',
            delay: 500,
            onWillStartDrag: (params) => this._sortFavStart(params),
            onDrop: (params) => this._sortFavDrop(params),
        });

        this.searchInput = useAutofocus();
        this.bmkBus = new EventBus();

        this.bmkConfig = bookmarkPalette;
        this.bmkConfig.providers = [
            { provide: (e) => bookmarkProvider(e, { recents: this.uo.recents }) }
        ];

        /* Bookmark command */
        useCommand(
            _t('Bookmark current view'),
            () => { bookmarkCurrentView(this); },
            {
                category: 'smart_action',
                isAvailable: () => this.actionService.currentController,
            }
        );

        useExternalListener(window, 'beforeunload', () => {
            /* Recents post process */
            this.uo.recents.forEach(el => {
                el._x = el._x || objectHash.MD5(el);
            });
            const uniqueArray = [];
            for (let index = this.uo.recents.length - 1; index >= 0; index--) {
                const el = this.uo.recents[index];
                if (uniqueArray.findIndex(o => o._x === el._x) == -1) {
                    uniqueArray.push(el);
                }
            }
            // Save to local context
            if (uniqueArray.length > MAX_RECENTS) {
                uniqueArray.length = MAX_RECENTS;
            }
            this.ue.recents = uniqueArray.reverse();

            /* Bookmark post process */
            if (this.ui.bookmarks.length == 0) {
                return;
            }
            const bookms = [];
            for (let index = this.ui.bookmarks.length - 1; index >= 0; index--) {
                const el = this.ui.bookmarks[index];
                if (bookms.findIndex(o => o._x === el._x) === -1) {
                    bookms.push(el);
                }
            }
            user.setUserSettings('up_bookmarks', JSON.stringify(bookms.reverse()));
        });

        onWillStart(async () => {
            const favMenus = JSON.parse(user.settings?.ps_fav_menus) || [];
            if (!favMenus.length && !this.ue.sidenav) {
                this.uState.ui_view = 'all_app';
            }
            this.uo.fav_menus = favMenus;
            this.ui.color_scheme = cookie.get('color_scheme');
        });

        useBus(this.env.bus, 'ACTION_MANAGER:UI-UPDATED', (mode) => {
            setTimeout(() => {
                let scrollEl = document.querySelector(`.nav-link.on[data-section="${this.currentApp?.id}"]`);
                scrollEl = scrollEl?.closest('.sidenav_group') || scrollEl;
                scrollEl?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'nearest',
                });
            }, 235);
        });

        useBus(this.env.bus, 'ISLAND:HM', ({ detail }) => {
            if (detail === false) {
                this.toggleLaunchpad();
                return;
            }
            this.uState.ui_view = this.uo.fav_menus.length ? 'app' : 'all_app';
            this.toggleLaunchpad();
        });

        useBus(this.env.bus, 'SUBNAV:PS', ({ detail }) => {
            if (detail) {
                this.computeSubnavPos(detail, true);
            }
        });

        useBus(this.env.bus, 'UDOO:FRC', ({ detail }) => {
            const obj = {
                res_model: detail.resModel,
                name: detail.displayName,
                res_id: detail.resId,
            }
            if (detail.viewId) obj.view_id = detail.viewId;
            if (this.currentApp?.name) obj._p = this.currentApp.name;

            this.uo.recents.push(obj);
            if (this.uo.recents.length > MAX_RECENTS) {
                this.uo.recents.shift();
            }
        });
    }

    computeSubnavPos(subNav, anim = false) {
        const currentRect = this.lastSubnavEl.getBoundingClientRect();

        const tPadding = 50;
        const bPadding = 10;

        const oSubNavCssText = subNav.style.cssText;
        subNav.style.visibility = 'hidden';
        subNav.style.display = 'block';
        const hPanel = subNav.offsetHeight;
        subNav.style.cssText = oSubNavCssText;

        const vBalance = (hPanel - currentRect.height) / 2;
        let alignedTop = currentRect.top - vBalance;

        if (alignedTop <= tPadding) {
            alignedTop = tPadding;
        } else if ((alignedTop + hPanel) >= (window.innerHeight - tPadding)) {
            alignedTop = 0;
        }

        const finalTop = alignedTop ? `${alignedTop}px` : null;
        const finalBottom = alignedTop ? null : `${bPadding}px`;
        const finalLeft = localization.direction === 'rtl' ? 'auto' : `${this.ue.sidenavWidth + 8}px`;
        const finalRight = localization.direction === 'rtl' ? `${this.ue.sidenavWidth + 8}px` : 'auto';

        Object.assign(subNav.style, { left: finalLeft, right: finalRight, top: finalTop, bottom: finalBottom });
    }

    get currentApp() {
        if (this.monkeyApp)
            return this.menuService.getMenu(this.monkeyApp);
        else
            return super.currentApp;
    }

    /**
     * @override
     */
    onAllAppsBtnClick() {
        super.onAllAppsBtnClick();
        this.toggleLaunchpad();
        this._closeAppMenuSidebar();
    }

    initIsland() {
        // Hack: Force a re-render to update the useRef for the dropdown workaround
        const bk = this.uState.ui_view;
        this.uState.ui_view = '';
        this.uState.ui_view = bk;

        // Hack: force fullscreen island mode without reactive mess
        if (this.ui.onceFullIsland) {
            this.uState.fullIsland = true;
            this.ui.onceFullIsland = false;
        } else {
            this.uState.fullIsland = false;
        }
    }

    toggleLaunchpad() {
        this.__owl__.bdom.el.querySelector('#island_toggler').click();
    }

    switchSpace(ev) {
        const el = ev.target.closest('.nav-link');
        if (this.uState.ui_view !== el.dataset.tab) {
            let uiView = el.dataset.tab;
            if (el.dataset.tab == 'pick') {
                uiView = this.uo.fav_menus.length ? 'app' : 'all_app';
            }
            this.uState.ui_view = uiView;
        }
        this._focusInput();
    }

    onIslandContext(ev) {
        const el = ev.target.closest('a');
        this.uState.currentMenuXmlid = el.dataset.menuXmlid;
        this.mapop.open(el, { widget: this });
    }

    async switchLang(lang) {
        if (lang === user.lang) return;

        await this.orm.write('res.users', [user.userId], { lang });
        this.ui.block();
        this.actionService.doAction('reload_context');
    }

    switchColorScheme(ev) {
        const target = this.ui.color_scheme === 'dark' ? 'light' : 'dark';
        cookie.set('color_scheme', target);
        this.ui.block();
        browser.location.reload();
    }

    onSearchExec() {
        if (this.uState.ui_view == 'space') {
            this.env.bus.trigger('BMK:SEARCH', this.searchInput.el.value);
        } else {
            const searchValue = `/${this.searchInput.el.value.trim()}`;
            this.searchInput.el.value = '';

            this.cmd.openMainPalette({ searchValue });
        }
    }

    isCurrentApp(app) {
        if (this.currentApp && app) return this.currentApp.id === app.id;
        return false;
    }

    onSelectMenu(app) {
        this.mipop.close();

        this.blockAutoSubnav = true;
        setTimeout(() => {
            this.blockAutoSubnav = false;
        }, 800);

        this.onNavBarDropdownItemSelection(app);
    }

    preSubnavTiming(ev, appsub) {
        ev.preventDefault();
        if (this.blockAutoSubnav) {
            return;
        }
        if (this.autoSubTimer) {
            clearTimeout(this.autoSubTimer);
            this.autoSubTimer = null;
        }

        const evTarget = ev.target.closest('.nav-item');
        const secondNav = document.querySelector('.sidenav_2nd');
        if (secondNav && this.lastSubnavEl === evTarget) {
            return;
        }

        if (secondNav) {
            if (ev.x > 0.66 * this.ue.sidenavWidth) {
                return;
            }
            this.autoSubTimer = setTimeout(() => {
                this.lastSubnavEl = evTarget;
                this.onShowSubnav(this.lastSubnavEl, appsub);
            }, 100);
        } else if (evTarget.firstChild.classList.contains('on')) {
            const subuid = appsub.map(node => node.id).join('');
            if (!document.querySelector(`.sidenav_2nd > ._${subuid}`)) {
                this.lastSubnavEl = evTarget;
                this.onShowSubnav(this.lastSubnavEl, appsub);
            }
        }
    }

    onMouseLeaveNavItem(ev) {
        if (this.autoSubTimer) {
            clearTimeout(this.autoSubTimer);
            this.autoSubTimer = null;
        }
    }

    onShowSubnav(ev, appsub, isCtx = false) {
        const subuid = '_' + appsub.map(node => node.id).join('');
        let el = ev;
        if (ev instanceof PointerEvent) {
            ev.preventDefault();
            ev.stopPropagation();
            el = ev.target;
        }
        if (this.blockAutoSubnav || (isCtx && document.querySelector(`.sidenav_2nd > .${subuid}`))) {
            return;
        }
        this.lastSubnavEl = el.closest('.nav-item');
        if (this.mipop.isOpen) {
            Object.assign(this.mipop.instance.props, { subuid, appsub });
            this.mipop.instance.render();
            return;
        }
        this.mipop.open(this.lastSubnavEl, {
            getMenuItemHref: (payload) => this.getMenuItemHref(payload),
            onSelectMenu: (menu) => {
                this.onSelectMenu(menu);
                queueMicrotask(() => { this.mipop.close(); });
            },
            self: this.mipop,
            subuid,
            appsub,
        });
    }

    async openRecentAction(action) {
        this.ui.block_recent = true;
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            view_mode: 'form',
            views: [[false, 'form']],
            ...action,
        });
    }

    getAppSections(id) {
        this.monkeyApp = id;
        const monkeySections = this.currentAppSections;
        this.monkeyApp = false;
        return monkeySections;
    }

    _sortFavStart({ element, addClass }) {
        addClass(element.children[0], 'u_dragged_app');
    }

    async _sortFavDrop({ element, previous }) {
        const order = this.uo.orderedApps.map((app) => app.xmlid);
        const xmlId = element.children[0].dataset.menuXmlid;
        const xmlIdIndex = order.indexOf(xmlId);

        order.splice(xmlIdIndex, 1);
        if (previous) {
            const prevIndex = order.indexOf(previous.children[0].dataset.menuXmlid);
            order.splice(prevIndex + 1, 0, xmlId);
        } else {
            order.splice(0, 0, xmlId);
        }

        // apply new order and sync
        reorderApps(this.uo.orderedApps, order);
        await user.setUserSettings('ps_menu_orders', JSON.stringify(order));
    }

    _focusInput() {
        if (this.searchInput.el) {
            setTimeout(() => {
                this.searchInput.el.focus();
            }, 77);
        }
    }
}

export class MenuAppContextMenu extends Component {
    static template = 'wub.MenuAppContextMenu';
    static props = { '*': true };

    contextPinStart() {
        const { uState, uo } = this.props.widget;
        return uo.fav_menus.includes(uState.currentMenuXmlid);
    }

    appinNewTab() {
        this.props.close();

        setTimeout(() => {
            const { uState, originApps, getMenuItemHref } = this.props.widget;
            const cApp = originApps.find((el) => el.xmlid === uState.currentMenuXmlid);
            if (cApp) window.open(getMenuItemHref(cApp), '_blank').focus();
        }, 77);
    }

    async pinToStart() {
        this.props.close();

        const { uState, uo } = this.props.widget;
        uo.fav_menus.push(uState.currentMenuXmlid);
        user.setUserSettings('ps_fav_menus', JSON.stringify(uo.fav_menus));

        this.props.widget.uState.ui_view = 'app';
    }

    async unpinFromStart() {
        this.props.close();

        const { uState, uo } = this.props.widget;
        const newFavs = uo.fav_menus.filter((o) => o !== uState.currentMenuXmlid);
        uo.fav_menus = newFavs;
        user.setUserSettings('ps_fav_menus', JSON.stringify(newFavs));
    }

    async setHomeAction() {
        this.props.close();

        const { uState, env } = this.props.widget;
        await user.setUserSettings('ps_start_xmlid', uState.currentMenuXmlid);
        env.services.notification.add(
            _t('Home action has been set!'),
            {
                title: _t('Notification'),
                type: 'success',
            }
        );
    }

    async pinThemAllStart() {
        this.props.close();

        const { uState, uo, originApps } = this.props.widget;
        const newFavs = originApps.map((app) => app.xmlid);
        uo.fav_menus = newFavs;
        await user.setUserSettings('ps_fav_menus', JSON.stringify(newFavs));
        uState.ui_view = 'app';
    }
}

export class SideNavSub extends Component {
    static components = { DropdownItem };
    static template = 'wub.Sidenav.2nd';
    static props = { '*': true };

    setup() {
        this.props.self.instance = this.__owl__.component;

        onPatched(() => {
            this.env.bus.trigger('SUBNAV:PS', this.__owl__.bdom?.parentEl);
        });
    }
}