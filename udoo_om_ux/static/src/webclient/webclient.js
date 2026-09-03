import { loadLanguages, _t } from '@web/core/l10n/translation';
import { user } from '@web/core/user';
import { patch } from '@web/core/utils/patch';
import { registry } from '@web/core/registry';
import { isMacOS } from '@web/core/browser/feature_detection';
import { useService, useBus } from '@web/core/utils/hooks';
import { WebClient } from '@web/webclient/webclient';
import { LazyComponent } from '@web/core/assets';
import { ResizablePanel } from '@web/core/resizable_panel/resizable_panel';
import { Component, onWillStart, onMounted, xml } from '@odoo/owl';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

import { CommandPalette } from './systray/quick_search';
import { OmuxNavBar } from './navbar/navbar';

const TG_MAP = { 'on': true, 'off': false };
const trayMenu = registry.category('systray');


patch(WebClient.prototype, {
    setup() {
        super.setup();

        this.ui = useService('ui');
        this.cpy = useService('company');
        this.hotkey = useService('hotkey');

        if (!this.hasOwnProperty('def_sidenav')) this.def_sidenav = true;
        if (!this.hasOwnProperty('def_full_iland')) this.def_full_iland = false;
        if (!this.hasOwnProperty('def_auto_hmenu')) this.def_auto_hmenu = false;

        this.uo = useUdooStore();
        this.ue = useUdooLocalStore({
            sidenav: !this.env.isSmall && this.def_sidenav,
            footnav: odoo.omux.navbar.footnav,
            sidenavWidth: odoo.omux.sidenav.def_width,
        });

        this.currentCompany = useService('company').currentCompany;

        /* Set web page title by config */
        if (odoo.omux.web.title_prefix) {
            this.title.setParts({ zopenerp: odoo.omux.web.title_prefix });
        }

        /* Quick action system tray */
        trayMenu.add('x_command', { Component: CommandPalette }, { sequence: 50 });

        onWillStart(async () => {
            // Sidenav is initially hidden
            document.body.classList.add('iui', 'nolside');

            this.uo.ps_auto_hmenu = TG_MAP[user.settings?.ps_auto_hmenu] ?? this.def_auto_hmenu;
            this.uo.ps_full_iland = TG_MAP[user.settings?.ps_full_iland] ?? this.def_full_iland;

            this.ui.bookmarks = this.parseBookmarks();
            const languages = await loadLanguages(this.orm);
            this.ui.languages = languages;

            this.ui.cpyId = () => this.cpyId;

            // Restore ui size from local
            if (this.ue.sett_uisize && this.ue.sett_uisize !== 0) {
                odoo.sett_uisize = this.ue.sett_uisize;
                this.ui.size = this.ue.sett_uisize;
                document.body.classList.add('uup');
            }
        });

        onMounted(() => {
            // Load recents from local
            if (this.ue.recents?.length) {
                this.uo.recents = this.ue.recents;
            }
            this._loadSidenavState();
        });

        /* Holding key handling */
        useBus(this.env.bus, 'ACTION_MANAGER:UI-UPDATED', (mode) => {
            // Clear key holding state
            this.ui.ctrlKey = false;
            this.ui.shiftKey = false;

            if (!this.ui.iuiFaced) {
                this.ui.iuiFaced = true;

                document.body.classList.remove('iui');
                document.querySelector('.o_sidenav')?.classList.remove('opacity-0');
            }
            if (document.querySelector('.o_popover.o_navbar_apps_menu')) {
                this.env.bus.trigger('ISLAND:HM', false);
            }
        });

        useBus(this.ui.bus, 'OMUX:TOPBAR', async (arg) => {
            this.onSassLsideFold(arg.detail);
        });
    },

    get cpyId() {
        return this.cpy.activeCompanyIds[0];
    },

    onGlobalClick(ev) {
        // Save ctrl holding state
        this.env.services.ui.ctrlKey = ev.ctrlKey || (isMacOS() && ev.metaKey);
        this.env.services.ui.shiftKey = ev.shiftKey;

        super.onGlobalClick(ev);
    },

    _loadSidenavState() {
        if (this.ue.sidenav) {
            document.body.classList.remove('nolside');
        } else {
            document.body.classList.add('nolside');
        }
    },

    async _loadDefaultApp() {
        // Get company menu preset for initial user
        const favconf = user.settings?.ps_fav_menus;
        if (!favconf || favconf == '[]') {
            this.uo.apps_preset = await this.orm.silent.call('res.company', 'get_menus_preset', [[this.currentCompany.id]]);
            if (this.uo.apps_preset) {
                const newfav = [];
                this.uo.orderedApps.forEach(app => {
                    if (this.uo.apps_preset.includes(app.id)) {
                        newfav.push(app.xmlid);
                    }
                });
                this.uo.fav_menus = newfav;
                await user.setUserSettings('ps_fav_menus', JSON.stringify(newfav));
            }
        }
        // Start action logic
        const root = this.menuService.getMenu('root');
        for (const app of root.childrenTree) {
            if (app.xmlid === user.settings?.ps_start_xmlid) {
                return this.menuService.selectMenu(app);
            }
        }
        this.ui.onceFullIsland = true;
        this.env.bus.trigger('ISLAND:HM');
    },

    _onSideNavResize(width) {
        const sidenav = document.querySelector('.o_sidenav');
        if (!sidenav) return;

        if (width > odoo.omux.sidenav.max_width) {
            width = odoo.omux.sidenav.max_width;
            sidenav.style.width = `${width}px`;
        }
        if (width < 142) {
            sidenav.classList.add('sm');
        } else {
            sidenav.classList.remove('sm');
        }

        this.ue.sidenavWidth = width;
        document.documentElement.style.setProperty('--uw-sidenav', `${width}px`);

        window.dispatchEvent(new Event('resize'));
    },

    toggleFootnav() {
        this.ue.footnav = !this.ue.footnav;
    },

    parseBookmarks() {
        return JSON.parse(user.settings?.up_bookmarks || '[]');
    },

    onSassLsideFold(forceVal = undefined) {
        if (forceVal !== undefined) this.ue.sidenav = forceVal;
        else this.ue.sidenav = !this.ue.sidenav && !this.env.isSmall;

        this._loadSidenavState();

        window.dispatchEvent(new Event('resize'));
    },

    openOmSearch() {
        this.env.services.command.openMainPalette({
            searchValue: '/',
            bypassEditableProtection: true,
            global: true,
        });
    }
});

WebClient.components = { ...WebClient.components, NavBar: OmuxNavBar, ResizablePanel }

export class OmuxConfLoader extends Component {
    static template = xml`<LazyComponent bundle="'omux.conf'" Component="'OmuxConf'"/>`;
    static components = { LazyComponent };
    static props = { '*': true };
}