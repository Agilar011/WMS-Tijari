import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { utils } from '@web/core/ui/ui_service';

patch(utils, {
    getSize() {
        if (odoo.force_uisize) {
            return odoo.force_uisize;
        }
        if (odoo.sett_uisize) {
            return Math.min(odoo.sett_uisize, super.getSize());
        }
        return super.getSize();
    },

    getPureSize() {
        return super.getSize();
    }
});