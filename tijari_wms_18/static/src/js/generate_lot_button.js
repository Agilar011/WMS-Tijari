/** @odoo-module **/
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { Component } from '@odoo/owl';
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class GenerateLotButton extends Component {
    static props = { ...standardFieldProps }; // Sangat disarankan di Odoo 18
    static template = "tijari.GenerateLotButton";

    setup() {
        this.orm = useService("orm");
    }

    onClick() {
        // Pada Odoo 18, field component menggunakan this.props.record.update
        this.props.record.update({ [this.props.name]: true });
    }
}

// PERBAIKAN UTAMA: Daftarkan sebagai objek dengan key 'component'
registry.category("fields").add("generate_lot_button", {
    component: GenerateLotButton,
});
