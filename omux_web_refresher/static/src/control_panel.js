import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useDebounced } from '@web/core/utils/timing';
import { useBus } from '@web/core/utils/hooks';
import { ControlPanel } from '@web/search/control_panel/control_panel';
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';

import { useFormStatusIndicatorState } from './form_indicator';

const REFRESH_KEY_FRAMES = [
    { opacity: 0.9, transform: 'none' },
    { opacity: 0, transform: 'translateY(17px)' },
    { opacity: 1, transform: 'none' },
];

patch(ControlPanel.prototype, {
    setup() {
        super.setup();

        this.formIndicatorState = useFormStatusIndicatorState();

        this.doRefresh = useDebounced(this.doRefresh, 200);

        useBus(this.env.bus, 'CTL:SL_REFR', () => this._doRefresh(true));
        useBus(this.env.bus, 'CTL:SSL_REFR', ({ detail }) => {
            if (detail?.skipOnDirty && this._isFormDirty()) return;
            this._doRefresh(true);
        });
    },

    _isFormDirty() {
        return this.env.config.viewType === 'form'
            && this.formIndicatorState?.displayButtons?.();
    },

    async doRefresh() {
        if (this._isFormDirty()) {
            return this.dialogService.add(ConfirmationDialog, {
                body: _t('There is unsaved data. Do you want to discard the changes and proceed?'),
                confirm: async () => {
                    await this.formIndicatorState.discard();
                    return this._doRefresh();
                },
            });
        }
        return this._doRefresh();
    },

    async _doRefresh(silent = false) {
        if (!silent) {
            this.root.el.closest('.o_action, .o_dialog')
                ?.querySelector('.o_content')
                ?.animate(REFRESH_KEY_FRAMES, { duration: 300, easing: 'ease-out' });
        }

        const { pagerProps, env, actionService } = this;
        const { searchModel } = env;

        if (pagerProps?.onUpdate) {
            const { limit, offset } = pagerProps;
            return pagerProps.onUpdate({ offset, limit });
        }
        if (searchModel?.search) {
            return searchModel.search();
        }
        return actionService.loadState();
    },
});
