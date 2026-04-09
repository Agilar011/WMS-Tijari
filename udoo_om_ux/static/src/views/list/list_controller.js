import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { ListController } from '@web/views/list/list_controller';

import { encodeRecordUrl } from '../../webclient/action_utils';


patch(ListController.prototype, {
    setup() {
        super.setup();

        this.ui = useService('ui');
    },

    get uPureOpenRecord() {
        return !this.ui.ctrlKey;
    },

    async openRecord(record) {
        const { ui, actionService } = this;
        const vController = actionService.currentController;
        if (this.uPureOpenRecord) {
            super.openRecord(record); return;
        }
        const hasFormView = vController.views?.some((view) => view.type === 'form');
        if (!hasFormView || this.archInfo.openAction || this.env.inDialog) {
            super.openRecord(record); return;
        }
        await this._validOpenRecordOm(record, ui, vController);
    },

    async _validOpenRecordOm(record, ui, vController) {
        if (ui.ctrlKey) {
            const act = encodeRecordUrl(record, vController.action);
            await this.actionService.doAction(act);
            return 'redir';
        }
        if (super._validOpenRecordOm) {
            await super._validOpenRecordOm(record, ui, vController);
        }
    },
});
