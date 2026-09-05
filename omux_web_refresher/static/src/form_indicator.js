/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { FormStatusIndicator } from '@web/views/form/form_status_indicator/form_status_indicator';
import { onWillRender, reactive, useState } from '@odoo/owl';

export const formIndicatorStore = reactive({});
export const useFormStatusIndicatorState = () => useState(formIndicatorStore);

function exposeFormStatus(getProps) {
    const state = useFormStatusIndicatorState();

    onWillRender(() => {
        Object.assign(state, getProps() || {});
    });
}

patch(FormStatusIndicator.prototype, {
    setup() {
        super.setup();

        exposeFormStatus(() => {
            if (!this.props.model.root.isNew) {
                return {
                    discard: async () => this.discard(),
                    indicatorMode: () => this.indicatorMode,
                    displayButtons: () => this.displayButtons,
                };
            }
        });
    },
});
