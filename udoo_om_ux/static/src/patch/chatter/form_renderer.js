/* @odoo-module */

import { patch } from '@web/core/utils/patch';
import { utils, SIZES } from '@web/core/ui/ui_service';
import { FormRenderer } from '@web/views/form/form_renderer';


patch(FormRenderer.prototype, {

    get uCommboSize() {
        const uiPureSize = utils.getPureSize();

        return uiPureSize != this.uiService.size && uiPureSize >= SIZES.XL && this.uiService.size == SIZES.XL && this.hasFile();
    },

    mailLayout(hasAttachmentContainer) {
        if (this.uCommboSize && hasAttachmentContainer) {
            return 'COMBO'; // chatter on the bottom, attachment on the side
        }
        return super.mailLayout(hasAttachmentContainer);
    },
});