import { patch } from '@web/core/utils/patch';
import { WebClient } from '@web/webclient/webclient';


patch(WebClient.prototype, {
    setup() {
        this.def_sidenav = false;
        super.setup();
    },
});