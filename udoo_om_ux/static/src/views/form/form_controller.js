import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { useState } from '@odoo/owl';
import { FormController } from '@web/views/form/form_controller';

patch(FormController.prototype, {
    setup() {
        super.setup();

        if (this.env.services['mail.store']) {
            this.uso = useState(useService('mail.store'));
        }
    },

    async create() {
        if (!this.uso.uQuickRepeat) {
            await super.create();
            return;
        }

        const canProceed = await this.model.root.save({
            onError: this.onSaveError.bind(this),
        });
        // FIXME: disable/enable not done in onPagerUpdate
        if (canProceed) {
            await this.duplicateRecord();
        }
    },

    async beforeLeave() {
        if (!this.model.root.isNew) {
            if (!this.ui.block_recent) {
                this.env.bus.trigger('UDOO:FRC', {
                    resId: this.props.resId,
                    resModel: this.props.resModel,
                    displayName: this.env.services.title.getParts().action,
                    viewId: this.env.config.viewId,
                });
            } else {
                this.ui.block_recent = false;
            }
        }
        return await super.beforeLeave();
    },
});