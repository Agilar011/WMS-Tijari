import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { router } from '@web/core/browser/router';
import { useService } from '@web/core/utils/hooks';
import { onWillRender, onWillUnmount } from '@odoo/owl';
import { KanbanController } from '@web/views/kanban/kanban_controller';
import { FormViewDialog } from '@web/views/view_dialogs/form_view_dialog';

import { encodeRecordUrl } from '../../webclient/action_utils';


patch(KanbanController.prototype, {
    setup() {
        super.setup();

        this.ui = useService('ui');

        onWillRender(async () => {
            const { ui, props } = this;
            if (props.context.ux_props?.dropin_kanban) {
                ui.dropinMode = true;
            }
        });

        onWillUnmount(() => {
            if (this.ui.dropinMode) {
                this.ui.dropinMode = false;
            }
        });
    },

    async openRecord(record) {
        if (this.env.inDialog || (!this.ui.dropinMode && !this.ui.ctrlKey && !this.ui.shiftKey)) {
            await super.openRecord(record); return;
        }

        const controller = this.actionService.currentController;
        const hasFormView = controller.views?.some((view) => view.type === 'form');

        if (!hasFormView) {
            await super.openRecord(record); return;
        }
        if (this.ui.ctrlKey) {
            const act = encodeRecordUrl(record, controller.action);
            await this.actionService.doAction(act);
            return;
        } else if (this.ui.shiftKey) {
            this.ui.dropinMode = true;
        }
        if (this.ui.dropinMode) {
            let sheetName = record._textValues.display_name || record._textValues.name || router.current.actionStack[router.current.actionStack.length - 1].displayName
            record.model.dialog.add(FormViewDialog, {
                size: 'xl',
                title: sheetName,
                context: { 'ucls': 'u_dsheet' },
                resModel: record.resModel,
                resId: record.resId,
                onRecordSaved: async () => {
                    await this.model.load();
                },
            });
        }
    },
});
