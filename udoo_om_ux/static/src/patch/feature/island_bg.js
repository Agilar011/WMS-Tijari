import { patch } from '@web/core/utils/patch';
import { onWillStart } from '@odoo/owl';

import { OmuxNavBar } from '@udoo_om_ux/webclient/navbar/navbar';


patch(OmuxNavBar.prototype, {
    setup() {
        super.setup();

        onWillStart(async () => {
            const companyId = this.ui.cpyId();
            const mobile = this.isMobileOS || this.env.isSmall;
            const backgroundField = await this.orm.call(
                'res.company',
                'get_home_background_field',
                [companyId, this.ui.color_scheme, mobile],
            );
            this.ownBrandBg = backgroundField
                ? `background-image: url('/web/image/res.company/${companyId}/${backgroundField}');background-size: cover;background-repeat: no-repeat;background-position: center;`
                : false;
        });
    },
});