import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { KanbanRenderer } from '@web/views/kanban/kanban_renderer';

import { useUdooLocalStore } from '@omux_state_manager/store';


patch(KanbanRenderer.prototype, {

    setup() {
        super.setup();
        this.ue = useUdooLocalStore();
    },
});