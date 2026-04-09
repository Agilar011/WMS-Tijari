import { patch } from '@web/core/utils/patch';
import { Dialog } from '@web/core/dialog/dialog';
import { onWillRender } from '@odoo/owl';

const SIZES = ['lg', 'xl', 'fs'];

patch(Dialog.prototype, {
    setup() {
        super.setup();
        this.uOrgSize = this.props.size;

        onWillRender(() => {
            if (this.uForceSize) {
                this.props.size = this.uForceSize;
            }
        });
    },

    toggle_dialog_size(ev) {
        const dialog = ev.target.closest('.modal-dialog');
        dialog.style.alignItems = 'unset';
        const formView = dialog.querySelector('.o_form_view');
        if (formView) {
            formView.style.height = '100%';
        }

        const inbackfs = this.props.size != 'fs';
        if (inbackfs) {
            this.uForceSize = 'fs';
        } else {
            this.uForceSize = this.uOrgSize;
            dialog.style.alignItems = null;
        }

        this.onResize();
        this.render();
    },

    switch_dialog_size() {
        let idx = SIZES.indexOf(this.props.size);
        if (idx === (SIZES.length - 1)) {
            this.uForceSize = this.uOrgSize;
        } else {
            this.uForceSize = SIZES[idx + 1];
        }
        this.render();
    },
});