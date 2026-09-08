import { _t } from '@web/core/l10n/translation';
import { registry } from '@web/core/registry';

import { OmuxConfLoader } from '../webclient/webclient';

const userMenuRegistry = registry.category('user_menuitems');

function customizeItem(env) {
    return {
        type: 'item',
        id: 'customize',
        description: _t('Appearance'),
        callback: () => {
            if (env.isSmall) {
                document.querySelector('.o_burger_menu .o_sidebar_close')?.click();
            }
            env.services.ui.omux_conf_ctab = 'usr';
            env.services.dialog.add(OmuxConfLoader, {});
        },
        sequence: 41,
    };
}

function separator42() {
    return {
        type: 'separator',
        sequence: 42,
    };
}

userMenuRegistry
    .add('appearance', customizeItem)
    .add('separator42', separator42)