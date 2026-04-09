import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { Chatter } from '@mail/chatter/web_portal/chatter';
import { useBus } from '@web/core/utils/hooks';

patch(Chatter.prototype, {
    setup() {
        super.setup();


        useBus(this.env.bus, 'CHR:SWITCH', (args) => {
            const formRenderer = document.querySelector('.o_form_renderer');
            const chatter = document.querySelector('.o-mail-Form-chatter');

            if (!this.props.isChatterAside || this.store.focusChatter === false) {
                if (args.detail == 'b') return;

                formRenderer.classList.remove('flex-column');
                formRenderer.classList.add('flex-nowrap', 'h-100');
                document.querySelector('.o_form_view.o_action')?.classList.add('o_xxl_form_view', 'h-100');
                chatter.classList.remove('mt-4', 'mt-md-0');
                chatter.classList.add('o-aside', 'w-print-100');
                this.store.focusChatter = true;
            } else {
                if (args.detail == 'r') return;

                formRenderer.classList.remove('flex-nowrap', 'h-100');
                formRenderer.classList.add('flex-column');
                document.querySelector('.o_form_view.o_action')?.classList.remove('o_xxl_form_view', 'h-100');
                chatter.classList.remove('o-aside', 'w-print-100');
                chatter.classList.add('mt-4', 'mt-md-0');
                document.querySelector('.o_form_view .o_form_sheet_bg').style.maxWidth = 'unset';
                this.store.focusChatter = false;
            }
            this.props.isChatterAside = !this.props.isChatterAside;
            this.render();
        });
    }
});