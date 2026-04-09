import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useState } from '@odoo/owl';
import { ListRenderer } from '@web/views/list/list_renderer';

import { useUdooStore, useUdooLocalStore } from '@omux_state_manager/store';


patch(ListRenderer.prototype, {

    setup() {
        super.setup();
        this.ue = useUdooLocalStore();
        this.uo = useUdooStore();
        this.uState = useState({});
    },

    getSortableIconClass(column) {
        const { orderBy } = this.props.list;
        const classNames = this.isSortable(column) ? ['ri-lr lh-1 my-auto pt-1pt text-dodger'] : ['d-none'];
        if (orderBy.length && orderBy[0].name === column.name) {
            classNames.push(orderBy[0].asc ? 'ri-arrow-down-line opacity-75' : 'ri-arrow-up-line opacity-75');
        } else {
            classNames.push('ri-arrow-down-line', 'opacity-0', 'opacity-75-hover');
        }

        return classNames.join(' ');
    },
});