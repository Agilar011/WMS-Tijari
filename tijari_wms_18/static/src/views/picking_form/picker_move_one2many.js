/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    StockMoveX2ManyField,
    stockMoveX2ManyField,
} from "@stock/views/picking_form/stock_move_one2many";

export class PickerMoveX2ManyField extends StockMoveX2ManyField {
    async openRecord(record) {
        if (this.canOpenRecord && !record.isNew) {
            const dirty = await record.isDirty();

            if (
                await record._parentRecord.isDirty() ||
                (dirty && "quantity" in record._changes)
            ) {
                await record._parentRecord.save({ reload: true });

                record = record._parentRecord.data[this.props.name].records.find(
                    (e) => e.resId === record.resId
                );

                if (!record) {
                    return;
                }
            }
        }

        if (this.canOpenRecord) {
            return this._openRecord({
                record,
                context: this.props.context,
                mode: "edit",
            });
        }
    }
}

export const pickerMoveX2ManyField = {
    ...stockMoveX2ManyField,
    component: PickerMoveX2ManyField,
};

registry.category("fields").add(
    "picker_move_one2many",
    pickerMoveX2ManyField
);