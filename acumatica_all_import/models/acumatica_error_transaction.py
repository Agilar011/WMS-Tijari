from odoo import api, fields, models


class AcumaticaErrorTransaction(models.Model):
    _name = 'acumatica.error.transaction'
    _description = 'Acumatica Transaction Error'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name')
    data_type = fields.Selection([
        ('acumatica.receipt.line', 'PO Receipt'),
        ('acumatica.inventory.recieved.line', 'Inventory Receive'),
        ('acumatica.transfer.line', 'SOTR Receipt'),
        ('acumatica.shipment.line', 'Shipment SO Return'),
        ('acumatica.receipt.external.line', 'Receipt External'),
        ('acumatica.transfer.shipment.line', 'Transfer Shipment'),
        ('acumatica.toko.pegang.do.line', 'Toko Pegang DO'),
        ('acumatica.receipt.change.item.line', 'Receipt Type Change Item'),
        ('acumatica.transfer.one.step.line', 'Transfer Pinjaman (1 Step)'),
        ('acumatica.transfer.two.step.line', 'Transfer Pinjaman (2 Step)'),
        ('acumatica.direct.transfer.staging', 'Direct Transfer'),
        ('acumatica.vendor.return.direct.transfer.staging', 'Vendor Return'),
        ('acumatica.credit.memo.consignment.staging', 'Credit Memo Consignment'),
        ('acumatica.invoice.consignment.staging', 'Invoice Consignment'),
        ('acumatica.inventory.issue.line', 'Inventory Issue'),
        ('acumatica.issue.line', 'Issue Type Change Item'),
        ('acumatica.issue.po.return.line', 'Issue Type PO Return'),
        ('acumatica.inventory.issue.toko.pegang.do.staging', 'Toko Pegang DO'),
        ('acumatica.inventory.receipt.transfer.wh.in.staging', 'Inventory Receipt Transfer WH In'),
        ('acumatica.kit.assembly', 'Kit Assembly'),
        ('acumatica.inventory.stock.line', 'Inventory Stock'),
        ('acumatica.shipment.gi.staging', 'Shipment GI'),
        ('acumatica.sales.order.shipment.staging', 'Sales Order Shipment'),
    ], string='Tipe Data')
    data_id = fields.Integer('Data ID')
    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('skipped', 'Dilewati (Sudah Ada)'),
        ('error', 'Error'),
        ('solved', 'Solved'),
    ], string='Status')
    error_msg = fields.Char('Log', tracking=True)

    def _get_transaction_name(self, record):
        for field_name in (
            'receipt_nbr',
            'reference_nbr',
            'shipment_nbr',
            'adt_ReferenceNbr',
            'adt_ShipmentNbr',
            'adt_ReceiptNbr',
            'name',
        ):
            value = getattr(record, field_name, False)
            if value:
                return value
        return record.display_name

    def _get_error_domain(self, record_or_origin):
        if hasattr(record_or_origin, '_name'):
            record = record_or_origin[:1]
            if not record:
                return []
            return [
                ('data_type', '=', record._name),
                ('data_id', '=', record.id),
            ]
        if record_or_origin:
            return [('name', '=', record_or_origin)]
        return []

    def _handle_acumatica_error(
        self,
        first,
        error_messages=False,
        api_acumatica=None,
        operation_type=None,
        origin=None,
        partner=None,
        location=None,
        location_dest=None,
        scheduled_date=None,
        total_qty=None,
        actual_qty=None,
        payload=None,
        line_payloads=None,
    ):
        if (
            not hasattr(first, '_name')
            and error_messages
            and not api_acumatica
            and not any([operation_type, origin, partner, location, location_dest, scheduled_date, total_qty, actual_qty, payload, line_payloads])
        ):
            api_acumatica = error_messages
            error_messages = False

        if not error_messages:
            domain = self._get_error_domain(first)
            if domain:
                self.search(domain).write({'import_state': 'solved'})
            return False

        if not first or not hasattr(first, '_name'):
            return False
        first = first[:1]
        if not first:
            return False

        error_messages = error_messages if isinstance(error_messages, (list, tuple)) else [error_messages]
        error_msg = '\n'.join(str(message) for message in error_messages if message)
        name = origin or self._get_transaction_name(first)
        error_data = self.search([
            ('data_type', '=', first._name),
            ('data_id', '=', first.id),
            ('import_state', '=', 'error'),
        ], limit=1)
        values = {
            'name': name,
            'data_type': first._name,
            'data_id': first.id,
            'import_state': 'error',
            'error_msg': error_msg[:1000],
        }
        if error_data:
            error_data.write(values)
        else:
            error_data = self.create(values)
        if 'acumatica_err_id' in first._fields:
            first.acumatica_err_id = error_data
        return error_data

    def _handle_acumatica_update(self, first, error_messages=False, **kwargs):
        if not first:
            return False
        if not hasattr(first, '_name'):
            domain = self._get_error_domain(first)
            if domain:
                self.search(domain).write({'import_state': 'solved'})
            return False

        first = first[:1]
        if not first:
            return False

        name = kwargs.get('origin') or self._get_transaction_name(first)
        update_data = self.search([
            ('data_type', '=', first._name),
            ('data_id', '=', first.id),
            ('import_state', '=', 'updated'),
        ], limit=1)
        values = {
            'name': name,
            'data_type': first._name,
            'data_id': first.id,
            'import_state': 'updated',
            'error_msg': error_messages or f'Updated: {name} in {fields.Datetime.now()}',
        }
        if update_data:
            update_data.write(values)
        else:
            update_data = self.create(values)
        return update_data

    def action_open_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Detail',
            'res_model': self.data_type,
            'res_id': self.data_id,
            'view_mode': 'form',
            'target': 'current',
        }
