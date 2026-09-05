import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { localization } from '@web/core/l10n/localization';
import { useBus, useService } from '@web/core/utils/hooks';
import { throttleForAnimation } from '@web/core/utils/timing';
import { onWillStart, useState, useExternalListener } from '@odoo/owl';
import { Layout } from '@web/search/layout';

import { useUdooLocalStore } from '@omux_state_manager/store';

const UW_ASIDE = '--Chatter-min-width';


patch(Layout.prototype, {
    setup() {
        super.setup();

        this.ue = useUdooLocalStore();
        this.ui = useService('ui');
        this.yy = useState({
            sashMarkPoint: 0,
            noaside: odoo.omux.chatter.def_hide,
        });

        useBus(this.env.bus, 'LYT:TCTT', () => {
            this.onSassAsideFold();
        });

        useBus(this.env.bus, 'LYT:RESET', () => {
            delete this.ue.sass_fv;
            document.documentElement.style.setProperty(UW_ASIDE, null);

            window.dispatchEvent(new Event('resize'));
        });

        this.onSassAsideChange = throttleForAnimation(this.onSassAsideChange.bind(this));

        useExternalListener(window, 'mousemove', this.onSassAsideChange);
        useExternalListener(window, 'mouseup', this.onSassAsideEnd);

        onWillStart(async () => {
            // Restore chatter size adjustment info if exist
            if (this.env.chatter && this.ue.sass_fv) {
                document.documentElement.style.setProperty(UW_ASIDE, `${this.ue.sass_fv}px`);
            }

            if (this.yy.noaside) {
                document.body.classList.add('noaside');
            }
        });
    },

    onSassAsideFold() {
        this.yy.noaside = !this.yy.noaside;
        document.body.classList.toggle('noaside');
        window.dispatchEvent(new Event('resize'));
    },

    onSassAsideStart(ev) {
        this.yy.sashMarkPoint = ev.x;
    },

    onSassAsideEnd() {
        this.yy.sashMarkPoint = 0;
    },

    onSassAsideChange(ev) {
        ev.stopPropagation();
        ev.preventDefault();

        if (this.yy.sashMarkPoint) {
            const fv = localization.direction === 'rtl' ? ev.view.innerWidth - (ev.view.innerWidth - ev.x) : ev.view.innerWidth - ev.x;
            document.documentElement.style.setProperty(UW_ASIDE, `${fv}px`);
            this.ue.sass_fv = fv;

            window.dispatchEvent(new Event('resize'));
        }
    },
});