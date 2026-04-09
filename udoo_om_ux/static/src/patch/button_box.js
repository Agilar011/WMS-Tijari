/* @odoo-module */

import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { ButtonBox } from '@web/views/form/button_box/button_box';
import { onWillRender } from '@odoo/owl';

import { useUdooLocalStore } from '@omux_state_manager/store';

patch(ButtonBox.prototype, {
    setup() {
        this.ue = useUdooLocalStore();
        const ui = useService('ui');

        onWillRender(() => {
            let maxVisibleButtons;

            // Force max visible buttons to 2
            if (this.env.searchModel?._context?.splited_form && ui.getSplitDir() != 'horizontal') {
                maxVisibleButtons = 2;
            } else if (odoo.omux && this['ue'] && this['ue']['sidenav']) {
                maxVisibleButtons = [0, 0, 0, 4, 4, 5, 6][ui.size] || 6;
            } else {
                maxVisibleButtons = [0, 0, 0, 7, 4, 5, 8][ui.size] ?? 8;
            }

            const allVisibleButtons = Object.entries(this.props.slots)
                .filter(([_, slot]) => this.isSlotVisible(slot))
                .map(([slotName]) => slotName);
            if (allVisibleButtons.length <= maxVisibleButtons) {
                this.visibleButtons = allVisibleButtons;
                this.additionalButtons = [];
                this.isFull = allVisibleButtons.length === maxVisibleButtons;
            } else {
                // -1 for "More" dropdown
                const splitIndex = Math.max(maxVisibleButtons - 1, 0);
                this.visibleButtons = allVisibleButtons.slice(0, splitIndex);
                this.additionalButtons = allVisibleButtons.slice(splitIndex);
                this.isFull = true;
            }
        });
    }
});