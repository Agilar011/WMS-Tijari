from odoo import models, fields
from odoo.exceptions import UserError


class AcumaticaInternalTransferService(models.AbstractModel):
    _name = 'acumatica.internal.transfer.service'
    _description = 'Acumatica Internal Transfer Import Helper'

    def _find_location_mapping(self, code, label):
        Mapping = self.env['stock.location.acumatica']
        clean_code = (code or '').strip()
        if not clean_code:
            raise UserError(f'{label} kosong.')

        mapping = Mapping.search([
            ('code', '=', clean_code),
            ('active', '=', True),
        ], limit=1)
        if not mapping:
            mapping = Mapping.search([
                ('name', '=', clean_code),
                ('active', '=', True),
            ], limit=1)
        if not mapping:
            raise UserError(f'{label} mapping tidak ditemukan di stock.location.acumatica: {clean_code}')
        if not mapping.odoo_location_id:
            raise UserError(f'{label} mapping belum punya Odoo location: {clean_code}')
        return mapping

    def classify(self, from_code, to_code, from_label='FromWarehouseID', to_label='ToWarehouseID'):
        from_mapping = self._find_location_mapping(from_code, from_label)
        to_mapping = self._find_location_mapping(to_code, to_label)
        source_location = from_mapping.odoo_location_id
        destination_location = to_mapping.odoo_location_id

        if source_location == destination_location:
            return {
                'status': 'skip',
                'message': f'Skipped: {from_label} dan {to_label} map ke Odoo location yang sama.',
                'from_mapping': from_mapping,
                'to_mapping': to_mapping,
                'source_location': source_location,
                'destination_location': destination_location,
                'transaction_type': False,
            }

        source_warehouse = from_mapping.odoo_building_id
        destination_warehouse = to_mapping.odoo_building_id
        transaction_type = 'inter_warehouse'
        if source_warehouse and destination_warehouse and source_warehouse == destination_warehouse:
            transaction_type = 'intra_warehouse'

        return {
            'status': 'import',
            'message': False,
            'from_mapping': from_mapping,
            'to_mapping': to_mapping,
            'source_location': source_location,
            'destination_location': destination_location,
            'transaction_type': transaction_type,
        }

    def get_or_create_transit_location(self):
        Location = self.env['stock.location']
        transit_location = Location.search([('usage', '=', 'transit')], limit=1)
        if not transit_location:
            transit_location = Location.create({
                'name': 'Transit',
                'usage': 'transit',
            })
        return transit_location

    def prepare_order(self, external_ref, source_location, destination_location, transaction_type, schedule_date=False, note=False, transfer_type='transfer_out'):
        InternalTransferOrder = self.env['internal.transfer.order']
        order = InternalTransferOrder.search([('external_ref', '=', external_ref)], limit=1)
        vals = {
            'external_ref': external_ref,
            'transaction_type': transaction_type,
            'transfer_type': transfer_type,
            'location_id': source_location.id,
            'location_dest_id': destination_location.id,
            'transit_location_id': self.get_or_create_transit_location().id,
            'schedule_date': schedule_date or fields.Datetime.now(),
            'validation_policy': 'validate_all',
            'note': note or False,
        }
        if order:
            if order.picking_ids:
                raise UserError(f'Transfer {external_ref} sudah memiliki picking, tidak bisa diupdate.')
            if order.state not in ('draft', 'cancel'):
                raise UserError(f'Transfer {external_ref} sudah ada di state {order.state}, tidak bisa diupdate.')
            order.move_ids.unlink()
            vals['state'] = 'draft'
            order.write(vals)
            return order, 'updated'

        return InternalTransferOrder.create(vals), 'imported'

    def create_order_move(self, order, product, qty, uom=False, name=False, description=False, extra_vals=False):
        Move = self.env['stock.move']
        vals = {
            'name': name or product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': uom.id if uom else product.uom_id.id,
            'location_id': order.location_id.id,
            'location_dest_id': order.location_dest_id.id,
            'internal_transfer_order_id': order.id,
            'description_picking': description or name or False,
        }
        if extra_vals:
            vals.update(extra_vals)
        vals = {key: value for key, value in vals.items() if key in Move._fields}
        return Move.create(vals)
