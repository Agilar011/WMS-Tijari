import { Component } from "@odoo/owl";

export class CommandPalette extends Component {
    static template = 'wub.CommandPalette';
    static props = { '*': true };

    openMainPalette() {
        this.env.services.command.openMainPalette()
    }
}
