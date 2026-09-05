import { patch } from '@web/core/utils/patch';
import { toRaw } from '@odoo/owl';
import { ListController } from '@web/views/list/list_controller';


patch(ListController.prototype, {
    async expandFoldGroups() {
        let groups = this.model.root.groups;
        let hasExpandable = false;

        while (groups.length) {
            if (groups.some(group => group._config.isFolded)) {
                hasExpandable = true;
                for (const group of groups) { toRaw(group)._config.isFolded = false; }
                break;
            }
            groups = groups.map(group => group.list.groups || []).flat();
        }
        if (hasExpandable) {
            // Monkey patch
            this.BK_MAX_NUMBER_OPENED_GROUPS = this.model.constructor.MAX_NUMBER_OPENED_GROUPS;
            this.model.constructor.MAX_NUMBER_OPENED_GROUPS = 77;
        } else {
            this.foldAllGroups();
        }
        await this.model.load();
        this.model.notify();

        // Revert monkey patch
        this.model.constructor.MAX_NUMBER_OPENED_GROUPS = this.BK_MAX_NUMBER_OPENED_GROUPS;
    },

    async foldAllGroups() {
        let groups = this.model.root.groups;
        while (groups.length) {
            for (const group of groups) { group.toggle(); }
            groups = groups.map(group => group.list.groups || []).flat();
        }
    }
});
