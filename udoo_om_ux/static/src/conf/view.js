import { _t } from '@web/core/l10n/translation';
import { user } from '@web/core/user';
import { cookie } from '@web/core/browser/cookie';
import { browser } from '@web/core/browser/browser';
import { loadCSS, loadJS } from '@web/core/assets';
import { registry } from '@web/core/registry';
import { utils } from '@web/core/ui/ui_service';
import { useService } from '@web/core/utils/hooks';
import { Dialog } from '@web/core/dialog/dialog';
import { CheckBox } from '@web/core/checkbox/checkbox';
import { SelectMenu } from '@web/core/select_menu/select_menu';
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { View } from '@web/views/view';
import { Component, markup, onWillStart, onMounted, useState, useRef, useExternalListener } from '@odoo/owl';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';

export const OM = {
    user_scheme: [
        { 'code': 'magenta', 'title': _t('Magenta'), 'color': '#714B67' },
        { 'code': 'rose', 'title': _t('Rose'), 'color': '#b25968' },
        { 'code': 'lime', 'title': _t('Lime'), 'color': '#66954f' },
        { 'code': 'green', 'title': _t('Green'), 'color': '#19876a' },
        { 'code': 'emerald', 'title': _t('Emerald'), 'color': '#0E837C' },
        { 'code': 'dodger', 'title': _t('Dodger'), 'color': '#2383af' },
        { 'code': 'sky', 'title': _t('Sky'), 'color': '#1e93c9' },
        { 'code': 'indigo', 'title': _t('Indigo'), 'color': '#665f99' },
        { 'code': 'pink', 'title': _t('Pink'), 'color': '#b16080' },
        { 'code': 'orange', 'title': _t('Orange'), 'color': '#ae6464' },
        { 'code': 'yellow', 'title': _t('Yellow'), 'color': '#a98357' },
    ],
    system_scheme: {
        'accent': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Primary Color'),
            pam: 'o-brand-primary',
        },
        'text': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Text Color'),
            pam: 'o-main-text-color',
        },
        'action': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Action Color'),
            pam: 'o-action',
        },
        'link': {
            nam: markup('<span class="fw-bold">Brand Colors</span>: Link Color'),
            pam: 'o-main-link-color',
        },
        'sidenav_text': {
            nam: markup('<span class="fw-bold">Sidebar Navigation</span>: Text Color'),
            pam: 'u-sidenav',
        },
        'sidenav_bg': {
            nam: markup('<span class="fw-bold">Sidebar Navigation</span>: Background'),
            pam: 'u-sidenav-bg',
        },
        'sidenav_sub': {
            nam: markup('<span class="fw-bold">Sidebar Navigation</span>: Active Color'),
            pam: 'u-sidenav-accent',
        },
        'o_text_success': {
            nam: markup('<span class="fw-bold">State Colors</span>: Success Text'),
            pam: 'u-text-success',
        },
        'o_text_info': {
            nam: markup('<span class="fw-bold">State Colors</span>: Info Text'),
            pam: 'u-text-info',
        },
        'o_text_warning': {
            nam: markup('<span class="fw-bold">State Colors</span>: Warning Text'),
            pam: 'u-text-warning',
        },
        'o_text_danger': {
            nam: markup('<span class="fw-bold">State Colors</span>: Danger Text'),
            pam: 'u-text-danger',
        },
        'o_success': {
            nam: markup('<span class="fw-bold">State Colors</span>: Success Fill'),
            pam: 'o-success',
        },
        'o_info': {
            nam: markup('<span class="fw-bold">State Colors</span>: Info Fill'),
            pam: 'o-info',
        },
        'o_warning': {
            nam: markup('<span class="fw-bold">State Colors</span>: Warning Fill'),
            pam: 'o-warning',
        },
        'o_danger': {
            nam: markup('<span class="fw-bold">State Colors</span>: Danger Fill'),
            pam: 'o-danger',
        },
    },
    extra_feat: [
        {
            k: 'ips',
            n: _t('Input Style'),
            d: {
                default: _t('Default'),
                underlined: _t('Underlined'),
                filled: _t('Filled'),
            }
        },
        {
            k: 'brd',
            n: _t('Border Radius'),
            d: {
                default: _t('Default'),
                sharp: _t('Sharp'),
                subtle: _t('Subtle'),
                moderate: _t('Moderate'),
                soft: _t('Soft'),
            }
        },
        {
            k: 'dsy',
            n: _t('List Density'),
            d: {
                default: _t('Default'),
                cozy: _t('Cozy'),
                roomy: _t('Roomy'),
            }
        },
        {
            k: 'ftz',
            n: _t('Font Size'),
            d: {
                default: _t('Default'),
                optimal: _t('Optimal'),
                comfort: _t('Comfort'),
                readable: _t('Readable'),
                large: _t('Large'),
            }
        },
    ],
    swatches: [
        '#0078FF',
        '#0085E0',
        '#0092C5',
        '#009FB0',
        '#00A99D',
        '#14A58A',
        '#29A383',
        '#39A072',
        '#518F6A',
        '#667F62',
        '#7B6AA4',
        '#8F5A87',
        '#A05A76',
        '#B25968',
        '#C4595A',

        '#0A1A2F',
        '#1A2A40',
        '#293548',
        '#2D3D4A',
        '#384556',
        '#464E59',
        '#53585F',
        '#5F5F5F',
        '#6A6560',
        '#766F66',
        '#816C60',
        '#89665C',
        '#744F52',
        '#5A4446',
        '#3D3D3D',
    ]
    ,
    uiz_desc: {
        VSM: _t('Underline input fields; Set default form list view to Kanban; Position Chatter at bottom; Hide Document Viewer by default'),
        SM: _t('Set default form list view to Kanban; Position Chatter at bottom; Hide Document Viewer by default'),
        MD: _t('Position Chatter at bottom; Hide Document Viewer by default'),
        LG: _t('Position Chatter at bottom; Hide Document Viewer by default'),
        XL: _t('Position Chatter at bottom; Document Viewer on right if present'),
        XXL: _t('Position Chatter and Document Viewer on right')
    },
    font_choices: [
        { label: 'Default (System)', value: 'default' },
        { label: 'Google Fonts: Alegreya Sans', value: 'Alegreya+Sans:ital,wght@0,300%3B0,400%3B0,500%3B0,700%3B1,300%3B1,400%3B1,500%3B1,700&display=swap' },
        { label: 'Google Fonts: Be Vietnam Pro', value: 'Be+Vietnam+Pro:ital,wght@0,100%3B0,200%3B0,300%3B0,400%3B0,500%3B0,600%3B0,700%3B1,100%3B1,200%3B1,300%3B1,400%3B1,500%3B1,600%3B1,700&display=swap' },
        { label: 'Google Fonts: Cairo', value: 'Cairo:wght@200..700&display=swap' },
        { label: 'Google Fonts: Cairo Play', value: 'Cairo+Play:wght@200..700&display=swap' },
        { label: 'Google Fonts: Exo', value: 'Exo:wght@200..700&display=swap' },
        { label: 'Google Fonts: Exo 2', value: 'Exo+2:wght@200..700&display=swap' },
        { label: 'Google Fonts: Glory', value: 'Glory:ital,wght@0,100..700%3B1,100..700&display=swap' },
        { label: 'Google Fonts: Gothic A1', value: 'Gothic+A1:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Fonts: IBM Plex Sans', value: 'IBM+Plex+Sans:wght@200..700&display=swap' },
        { label: 'Google Fonts: IBM Plex Sans Arabic', value: 'IBM+Plex+Sans+Arabic:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Fonts: IBM Plex Sans Hebrew', value: 'IBM+Plex+Sans+Hebrew:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Fonts: IBM Plex Sans JP', value: 'IBM+Plex+Sans+JP:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Fonts: IBM Plex Sans KR', value: 'IBM+Plex+Sans+KR:wght@200%3B300%3B400%3B500%3B600%3B700&display=swap' },
        { label: 'Google Fonts: Inter', value: 'Inter:wght@200..700&display=swap' },
        { label: 'Google Fonts: Josefin Sans', value: 'Josefin+Sans:wght@200..700&display=swap' },
        { label: 'Google Fonts: Karla', value: 'Karla:wght@200..700&display=swap' },
        { label: 'Google Fonts: Lato', value: 'Lato:ital,wght@0,100%3B0,300%3B0,400%3B0,700%3B1,100%3B1,300%3B1,400%3B1,700&display=swap' },
        { label: 'Google Fonts: Mada', value: 'Mada:wght@200..700&display=swap' },
        { label: 'Google Fonts: Manrope', value: 'Manrope:wght@200..700&display=swap' },
        { label: 'Google Fonts: Merriweather Sans', value: 'Merriweather+Sans:wght@300..700&display=swap' },
        { label: 'Google Fonts: Montserrat', value: 'Montserrat:ital,wght@0,100..900%3B1,100..900&display=swap' },
        { label: 'Google Fonts: Mulish', value: 'Mulish:wght@200..700&display=swap' },
        { label: 'Google Fonts: Noto Kufi Arabic', value: 'Noto+Kufi+Arabic:wght@200..700&display=swap' },
        { label: 'Google Fonts: Noto Sans', value: 'Noto+Sans:wght@200..700&display=swap' },
        { label: 'Google Fonts: Noto Sans Georgian', value: 'Noto+Sans+Georgian:wght@200..700&display=swap' },
        { label: 'Google Fonts: Noto Sans JP', value: 'Noto+Sans+JP:wght@200..700&display=swap' },
        { label: 'Google Fonts: Noto Sans SC', value: 'Noto+Sans+SC:wght@200..700&display=swap' },
        { label: 'Google Fonts: Nunito', value: 'Nunito:ital,wght@0,200..700%3B1,200..700&display=swap' },
        { label: 'Google Fonts: Nunito Sans', value: 'Nunito+Sans:ital,opsz,wght@0,6..12,200..700%3B1,6..12,200..700&display=swap' },
        { label: 'Google Fonts: Open Sans', value: 'Open+Sans:ital,wght@0,300..700%3B1,300..700&display=swap' },
        { label: 'Google Fonts: Oswald', value: 'Oswald:wght@200..700&display=swap' },
        { label: 'Google Fonts: Oxanium', value: 'Oxanium:wght@200..700&display=swap' },
        { label: 'Google Fonts: Plus Jakarta Sans', value: 'Plus+Jakarta+Sans:wght@200..700&display=swap' },
        { label: 'Google Fonts: Poppins', value: 'Poppins:ital,wght@0,200%3B0,300%3B0,400%3B0,500%3B0,600%3B0,700%3B1,200%3B1,300%3B1,400%3B1,500%3B1,600%3B1,700&display=swap' },
        { label: 'Google Fonts: Prompt', value: 'Prompt:ital,wght@0,200%3B0,300%3B0,400%3B0,500%3B0,600%3B0,700%3B1,200%3B1,300%3B1,400%3B1,500%3B1,600%3B1,700&display=swap' },
        { label: 'Google Fonts: Quicksand', value: 'Quicksand:wght@500..700&display=swap' },
        { label: 'Google Fonts: Rajdhani', value: 'Rajdhani:wght@500%3B600%3B700&display=swap' },
        { label: 'Google Fonts: Raleway', value: 'Raleway:ital,wght@0,100..700%3B1,100..700&display=swap' },
        { label: 'Google Fonts: Roboto', value: 'Roboto:ital,wght@0,100..700%3B1,100..700&display=swap' },
        { label: 'Google Fonts: Roboto Condensed', value: 'Roboto+Condensed:wght@200..700&display=swap' },
        { label: 'Google Fonts: Roboto Flex', value: 'Roboto+Flex:opsz,wght@8..144,200..700&display=swap' },
        { label: 'Google Fonts: Roboto Slab', value: 'Roboto+Slab:wght@200..700&display=swap' },
        { label: 'Google Fonts: Rubik', value: 'Rubik:wght@300..700&display=swap' },
        { label: 'Google Fonts: Source Sans Pro', value: 'Source+Sans+3:ital,wght@0,200..700%3B1,200..700&display=swap' },
        { label: 'Google Fonts: Space Grotesk', value: 'Space+Grotesk:wght@300..700&display=swap' },
        { label: 'Google Fonts: Syne', value: 'Syne:wght@400..700&display=swap' },
        { label: 'Google Fonts: Tajawal', value: 'Tajawal:wght@300%3B400%3B500%3B700&display=swap' },
        { label: 'Google Fonts: Ubuntu', value: 'Ubuntu:wght@400%3B500%3B700&display=swap' },
        { label: 'Google Fonts: Work Sans', value: 'Work+Sans:wght@200..700&display=swap' },
        { label: 'Google Fonts: Zen Kaku Gothic Antique', value: 'Zen+Kaku+Gothic+Antique:wght@300%3B400%3B500%3B700%3B900&display=swap' },
        { label: 'Google Fonts: Zen Kaku Gothic New', value: 'Zen+Kaku+Gothic+New:wght@300%3B400%3B500%3B700%3B900&display=swap' },
        { label: 'Google Fonts: Zen Maru Gothic', value: 'Zen+Maru+Gothic:wght@300%3B400%3B500%3B700%3B900&display=swap' },
    ],
    toggler: { 'on': true, 'off': false },
}

export class OmuxConf extends Component {
    static template = 'wub.OmuxConf';
    static components = { CheckBox, Dialog, SelectMenu, View };
    static props = { '*': true };

    setup() {
        this.user = user;
        this.browser = browser;
        this.uiUtils = utils;

        this.ui = useService('ui');
        this.orm = useService('orm');
        this.dialog = useService('dialog');
        this.action = useService('action');
        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();

        this.o_accent = '#05869c';
        this.o_color_shade = cookie.get('color_shade');
        this.o_color_scheme = this.ui.color_scheme || 'light';
        this.o_ps_auto_hmenu = OM.toggler[user.settings?.ps_auto_hmenu];
        this.o_ps_full_iland = OM.toggler[user.settings?.ps_full_iland];

        this.state = useState({
            color_shade: this.o_color_shade,
            color_scheme: this.o_color_scheme,
            ctab: this.ui.omux_conf_ctab || 'sys',
        });

        delete this.ui.omux_conf_ctab;

        this.uiSizes = { VSM: 1, SM: 2, MD: 3, LG: 4, XL: 5, XXL: 6, Auto: 0 };
        this.uiTooltip = OM.uiz_desc;
        this.fontChoices = OM.font_choices;
        this.extraFeat = OM.extra_feat;

        this.defs = OM.system_scheme;
        for (const cl in OM.system_scheme) {
            this[`cp_${cl}`] = useRef(cl);
            this[`cp_dark_${cl}`] = useRef(`dark_${cl}`);
        }

        onWillStart(async () => {
            this.hasGroupOmux = await user.hasGroup('udoo_om_ux.group_omux');

            if (this.hasGroupOmux) {
                await this.sysOnInit();
            }
            this.schemeData = [
                { 'code': '', 'title': _t('Default'), 'color': this.o_accent },
                ...OM.user_scheme,
            ];
        });

        onMounted(() => {
            if (this.hasGroupOmux) {
                for (const cl in OM.system_scheme) {
                    this.iniPickr(cl, `cp_${cl}`);
                    this.iniPickr(`dark_${cl}`, `cp_dark_${cl}`);
                }
            }
        });

        useExternalListener(
            document,
            'pointerdown',
            this.onAdvMouseDown.bind(this)
        );
    }

    async sysOnInit() {
        const otopKeys = ['g_ips', 'g_brd', 'g_dsy', 'g_ftz', 'g_fty'];
        const ipsState = await this.orm.searchRead(
            'ir.asset',
            [
                '|',
                ['path', 'ilike', 'omux_input_style'],
                '|',
                ['path', 'ilike', 'omux_border_radius'],
                '|',
                ['path', 'ilike', 'omux_list_density'],
                ['path', 'ilike', 'feature/island_bg'],
            ],
            ['path', 'active'],
            { context: { active_test: false } }
        );

        otopKeys.forEach(key => this[key] = 'default');
        this.g_wbg = false;

        for (const o of ipsState) {
            if (!o.active) {
                continue;
            }
            if (o.path.endsWith('filled.scss')) {
                this.g_ips = 'filled';
            }
            else if (o.path.endsWith('underlined.scss')) {
                this.g_ips = 'underlined';
            }
            else if (o.path.endsWith('sharp')) {
                this.g_brd = 'sharp';
            }
            else if (o.path.endsWith('subtle')) {
                this.g_brd = 'subtle';
            }
            else if (o.path.endsWith('moderate')) {
                this.g_brd = 'moderate';
            }
            else if (o.path.endsWith('soft')) {
                this.g_brd = 'soft';
            }
            else if (o.path.endsWith('cozy.scss')) {
                this.g_dsy = 'cozy';
            }
            else if (o.path.endsWith('roomy.scss')) {
                this.g_dsy = 'roomy';
            }
            else if (o.path.endsWith('island_bg.js')) {
                this.g_wbg = true;
            }
        }

        let ffStates = await this.orm.searchRead('ir.asset', [['path', '=', '/_omux/backend_font.scss']], ['name']);
        for (const rec of ffStates) {
            rec.name.replace(/Font:\s*([^|]+)/i, (_, val) => this.g_fty = val.trim());
            rec.name.replace(/Size:\s*([^|]+)/i, (_, val) => this.g_ftz = val.trim());
        }

        // Assign option state
        otopKeys.forEach(key => { this.state[key] = this[key]; });
        this.state.g_wbg = this.g_wbg;

        // Load Pickr assets
        await loadJS('/omux_shared_lib/static/lib/pickr/pickr.min.js');
        await loadCSS('/omux_shared_lib/static/lib/pickr/classic.min.css');

        const scVars = Object.values(OM.system_scheme).map(o => o.pam);
        const scMapd = await this.orm.call('web_editor.assets', 'extf_omux_scheme', [scVars]);
        for (const [cl, info] of Object.entries(OM.system_scheme)) {
            ['', 'dark_'].forEach((prefix, i) => {
                const key = `${prefix}${cl}`;
                this[`o_${key}`] = scMapd[i][info.pam];
                this.state[key] = this[`o_${key}`];
            });
        }

        const cuv = await this.orm.searchRead('ir.ui.view', [['name', '=', 'omux.config.base']], ['id']);
        this.lmisProps = {
            type: 'list',
            resModel: 'ir.asset',
            display: { controlPanel: false },
            domain: [
                ['name', 'ilike', '[OMUX]'],
                ['name', 'not ilike', '/%/'],
                ['name', 'not ilike', '[OMUX]%Font:%'],
                ['name', 'not ilike', '[OMUX]%Size:%'],
                ['name', 'not ilike', '[OMUX] Border Radius:%'],
                ['name', 'not ilike', '[OMUX] List Density:%'],
                ['name', 'not ilike', '[OMUX] Input Style:%'],
                ['name', 'not ilike', '[OMUX] Backend: Island%'],
                ['name', 'not ilike', '[OMUX] Remove Light in Dark%'],
                '|',
                ['active', '=', true],
                ['active', '=', false],
            ],
            allowSelectors: false,
            viewId: cuv[0].id,
            className: 'thoem',
        }
    }

    onAdvMouseDown(ev) {
        if (ev.target.closest('.o_field_boolean_toggle')) {
            this.hasAdvChanged = true;
        }
    }

    iniPickr(cl, ref) {
        const pickr = Pickr.create({
            el: this[ref].el,
            theme: 'classic',
            default: this.state[cl],
            position: 'top-end',
            useAsButton: true,
            padding: 10,

            swatches: OM.swatches,

            components: {

                // Main components
                preview: true,
                opacity: true,
                hue: true,

                // Input / output Options
                interaction: {
                    hex: true,
                    rgba: true,
                    hsla: true,
                    input: true,
                    save: true,
                }
            }
        });
        pickr.on('save', (color, instance) => {
            instance.hide();
            this.state[cl] = color.toHEXA().toString();
        });
    }

    switchTab(ev) {
        this.state.ctab = ev.target.dataset.tab;
    }

    onUoOptionChanged(key, val) {
        this.uo[key] = val;
    }

    onUiSize(size) {
        if (odoo.sett_uisize !== size) {
            if (size === 0) {
                delete odoo.sett_uisize;
                this.ui.size = utils.getSize();
            } else {
                odoo.sett_uisize = size;
                this.ui.size = size;

                document.body.classList.add('uup');
            }
            // Local saver
            this.ue.sett_uisize = size;
        }
    }

    triggerTopbar(value) {
        this.ui.bus.trigger('OMUX:TOPBAR', !value);
    }

    async assetActiv(basePath, targetPath) {
        const assetModel = 'ir.asset';

        // Disable all records matching the basePath
        let allRecords = await this.orm.searchRead(assetModel, [['path', 'ilike', basePath]], ['id']);
        await this.orm.write(assetModel, allRecords.map(o => o.id), { active: false });

        // Enable the records corresponding to the stateValue
        if (targetPath) {
            let targetRecords = await this.orm.searchRead(
                assetModel,
                [['path', 'ilike', targetPath]],
                ['id'],
                { context: { active_test: false } }
            );
            await this.orm.write(assetModel, targetRecords.map(o => o.id), { active: true });
        }

        // Reload assets
        this.ui.block();
    }

    openCompanySett() {
        if (!this.user.isSystem) {
            return this.env.services.notification.add(
                _t('Contact the administrator for access.'),
                {
                    title: _t('Notification'),
                    type: 'warning',
                }
            );
        }
        this.action.doAction({
            name: _t('Company Branding'),
            type: 'ir.actions.act_window',
            res_model: 'res.company',
            res_id: this.ui.cpyId(),
            views: [[false, 'form']],
            target: 'new',
        });

        queueMicrotask(() => {
            document.querySelector('.modal-body.o_act_window div[name="logo_dui"]')?.scrollIntoView({
                behavior: 'smooth'
            });
        });
    }

    openAppMenuManager() {
        if (!this.user.isSystem) {
            return this.env.services.notification.add(
                _t('Contact the administrator for access.'),
                {
                    title: _t('Notification'),
                    type: 'warning',
                }
            );
        }
        this.env.dialogData.close();
        this.action.doAction({
            name: _t('App Menu Manager'),
            type: 'ir.actions.act_window',
            res_model: 'ir.ui.menu',
            views: [[false, 'list'], [false, 'form']],
            view_mode: "list,form",
            context: {
                search_default_root: 1,
            },
        });
    }

    clearBookmarks() {
        return new Promise((resolve) => {
            const confirm = async () => {
                this.ui.bookmarks = [];
                await user.setUserSettings('up_bookmarks', '[]');
                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    clearRecents() {
        return new Promise((resolve) => {
            const confirm = async () => {
                this.ue.recents = [];
                this.uo.recents = [];
                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    resetHomeAction() {
        return new Promise((resolve) => {
            const confirm = async () => {
                await user.setUserSettings('ps_start_xmlid', null);

                this.env.services.notification.add(
                    _t('Your home menu action has been restored.'),
                    {
                        title: _t('Notification'),
                        type: 'success',
                    }
                );

                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    resetHomeLayout() {
        return new Promise((resolve) => {
            const confirm = async () => {
                await user.setUserSettings('ps_menu_orders', null);
                await user.setUserSettings('ps_fav_menus', null);
                this.uo.fav_menus = [];

                this.env.services.notification.add(
                    _t('Your home menu layout has been restored.'),
                    {
                        title: _t('Notification'),
                        type: 'success',
                    }
                );

                resolve(true);
            };
            this.dialog.add(ConfirmationDialog, {
                body: _t('This action cannot be undone. Are you sure?'),
                confirm,
                cancel: () => resolve(false),
            });
        });
    }

    async confirm() {
        if (this.state.color_shade !== this.o_color_shade) {
            cookie.set('color_shade', this.state.color_shade);
            this.ui.block();
        }

        // User
        if (this.uo.ps_auto_hmenu !== this.o_ps_auto_hmenu) {
            await user.setUserSettings('ps_auto_hmenu', this.uo.ps_auto_hmenu ? 'on' : 'off');
            this.ui.unblock();
        }
        if (this.uo.ps_full_iland !== this.o_ps_full_iland) {
            await user.setUserSettings('ps_full_iland', this.uo.ps_full_iland ? 'on' : 'off');
            this.ui.unblock();
        }

        // System
        if (this.hasGroupOmux) {
            if (this.g_ips !== this.state.g_ips) {
                await this.assetActiv('omux_input_style', `omux_input_style/static/src/${this.state.g_ips}`);
            }
            if (this.g_brd !== this.state.g_brd) {
                await this.assetActiv('omux_border_radius', `omux_border_radius/${this.state.g_brd}`);
            }
            if (this.g_dsy !== this.state.g_dsy) {
                await this.assetActiv('omux_list_density', `omux_list_density/static/src/${this.state.g_dsy}`);
            }
            if (this.g_wbg !== this.state.g_wbg) {
                await this.assetActiv('feature/island_bg', this.state.g_wbg && 'feature/island_bg');
            }

            const lightDict = {};
            const darkDict = {};

            for (const [cl, info] of Object.entries(OM.system_scheme)) {

                if (this[`o_${cl}`] !== this.state[cl]) {
                    lightDict[cl] = [info.pam, this.state[cl]];
                }
                if (this[`o_dark_${cl}`] !== this.state[`dark_${cl}`]) {
                    darkDict[cl] = [info.pam, this.state[`dark_${cl}`]];
                }
            }

            if (Object.keys(lightDict).length || Object.keys(darkDict).length) {
                this.ui.block();
                try {
                    if (Object.keys(lightDict).length)
                        await this.orm.call('web_editor.assets', 'repr_omux_scheme', [lightDict]);
                    if (Object.keys(darkDict).length)
                        await this.orm.call('web_editor.assets', 'repr_omux_scheme', [darkDict, true]);
                } catch (error) {
                    console.error('Error saving SCSS changes:', error);
                }
            }

            let isNewFont = this.g_fty !== this.state.g_fty;
            let isNewFontSize = this.g_ftz !== this.state.g_ftz;
            if (isNewFont || isNewFontSize) {
                const params = {};
                if (isNewFont) {
                    params.fk = this.state.g_fty;
                }
                if (isNewFontSize) {
                    params.fs = this.state.g_ftz;
                }
                await this.orm.call('web_editor.assets', 'repr_omux_font', [params]);
                this.ui.block();
            }
        }

        if (this.hasAdvChanged) {
            this.ui.block();
        }

        if (this.ui.isBlocked) {
            browser.location.reload();
        } else {
            this.env.dialogData.close();
        }
    }

    async reset() {
        this.ui.block();
        const pattern = Object.entries(OM.system_scheme).map(([k, o]) => o.pam).join('|');
        await this.orm.call('web_editor.assets', 'reset_omux_light', [pattern]);
        await this.orm.call('web_editor.assets', 'reset_omux_dark', [pattern]);
        browser.location.reload();
    }
}

registry.category('lazy_components').add('OmuxConf', OmuxConf);