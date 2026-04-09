import { patch } from '@web/core/utils/patch';
import { onWillStart } from '@odoo/owl';

import { OmuxNavBar } from '@udoo_om_ux/webclient/navbar/navbar';


patch(OmuxNavBar.prototype, {
    setup() {
        super.setup();

        onWillStart(() => {
            this.ownBrandBg = `background-image: url('/web/image/res.company/${this.ui.cpyId()}/${this.ui.color_scheme == 'dark' ? 'bg_lui' : 'bg_dui'}');background-size: cover;background-repeat: no-repeat;background-position: center;`;
        });
    },
});