from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging

_logger = logging.getLogger(__name__)


class AcumaticaKitAssemblyLine(models.Model):
    """
    Tabel staging: hasil tarikan data Kit Assembly dari Acumatica.
    Target model Odoo: product.template

    Mapping:
      InventoryID          → default_code              (Mandatory)
      Description          → name                      (Mandatory)
      ItemType             → type                      (Mandatory)
      ItemClass            → adt_item_class             (Mandatory, to be)
      ItemStatus           → adt_item_status            (Mandatory, to be)
      BaseUOM              → uom_id / uom_po_id         (Mandatory, lookup by name)
      ValuationMethod      → adt_valuation_method       (Mandatory, to be)
      LastModifiedDateTime → adt_last_modified_datetime (Mandatory, to be)
    """
    _name        = 'acumatica.kit.assembly.line'
    _description = 'Data Kit Assembly dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # 'external_id':item.get("id", "") or "",
    # 'row_number': item.get("rowNumber", 0),
    # 'description': val(item, "Description"),
    # 'inventory_id': val(item, "InventoryID"),
    # 'last_modified_datetime': val(item, "LastModifiedDateTime"),
    # 'location': val(item, "Location"),
    # 'post_period': val(item, "PostPeriod"),
    # 'quantity': val(item, "Qty"),
    # 'reason_code':val(item, "ReasonCode"),
    # 'reference_nbr':val(item, "ReferenceNbr"),
    # 'requested_on':val(item, "RequestedOn"),
    # 'revision':val(item, "Revision"),
    # 'status':val(item, "Status"),
    # 'type':val(item, "Type"),
    # 'uom': val(item, "UOM"),
    # 'warehouse': val(item, "Warehouse"),


    # 'line_external_id': component.get('id', '') or '',
    # 'line_note': component.get('note', {}).get('value', '') or '',
    # 'inventory_id': self._val(component, 'InventoryID'),
    # 'line_nbr': str(line_nbr),
    # 'line_location_id': self._val(component, 'LocationID'),
    # 'line_reason_code': self._val(component, 'ReasonCode'),
    # 'stock_inventory_id': self._val(component, 'StockInventoryID'),
    # 'uom_code': self._val(component, 'UOM'),

    # ─── Data mentah dari Acumatica ──────────────────
    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Acumatica', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime', readonly=True)
    location = fields.Char(string='Location', readonly=True)
    post_period = fields.Char(string='PostPeriod', readonly=True)
    quantity = fields.Char(string='Qty', readonly=True)
    reason_code = fields.Char(string='ReasonCode', readonly=True)
    reference_nbr = fields.Char(string='ReferenceNbr', readonly=True)
    requested_on = fields.Char(string='RequestedOn', readonly=True)
    revision = fields.Char(string='Revision', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    type = fields.Char(string='Type', readonly=True)
    uom = fields.Char(string='uom', readonly=True)
    warehouse = fields.Char(string='Warehouse', readonly=True)

    line_external_id = fields.Char(string='Line UUID', readonly=True)
    line_note = fields.Char(string='Line Note', readonly=True)
    line_inventory_id = fields.Char(string='Line InventoryID', readonly=True)
    line_component_qty = fields.Char(string='Line Component Qty', readonly=True)
    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    line_location_id = fields.Char(string='Line LocationID', readonly=True)
    line_quantity = fields.Char(string='Line Quantity', readonly=True)
    line_reason_code = fields.Char(string='Line ReasonCode', readonly=True)
    stock_inventory_id = fields.Char(string='Stock InventoryID', readonly=True)
    line_uom = fields.Char(string='Line UOM', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message   = fields.Char(string='Keterangan',         readonly=True)
    odoo_product_id  = fields.Many2one('product.template', string='Product di Odoo', readonly=True)
    odoo_bom_id = fields.Many2one('mrp.bom', string='BOM di Odoo', readonly=True)
    selected         = fields.Boolean(string='Pilih',           default=True)

    config_id = fields.Many2one(
        'acumatica.stock.item.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # ─── Helpers ─────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    # ItemType Acumatica → type Odoo
    # 'consu' = storable/consumable (Odoo 17/18 pakai 'consu' untuk goods)
    ITEM_TYPE_MAP = {
        'finished good': 'consu',
        'component':     'consu',
        'non-stock':     'consu',
        'service':       'service',
        'labor':         'service',
        'charge':        'service',
    }

    # ValuationMethod Acumatica → adt_valuation_method selection
    VALUATION_MAP = {
        'FIFO':     'FIFO',
        'Average':  'Average',
        'Standard': 'Standard',
        'Specific': 'Specific',
    }

    # ItemStatus Acumatica → adt_item_status selection
    STATUS_MAP = {
        'Active':       'Active',
        'Inactive':     'Inactive',
        'ToDelete':     'ToDelete',
        'NoSales':      'NoSales',
        'NoPurchases':  'NoPurchases',
        'NoRequest':    'NoRequest',
    }

    def _resolve_uom(self, uom_name):
        """
        Lookup uom.uom by name (case-insensitive).
        UOM sudah diimport sebelumnya ke uom.uom.
        Return: uom.uom record atau browse() jika tidak ditemukan.
        """
        if not uom_name:
            return self.env['uom.uom'].browse()
        uom = self.env['uom.uom'].search([('name', '=ilike', uom_name)], limit=1)
        return uom

    def _find_existing_product(self, rec):
        """Cari product.template by default_code (InventoryID)."""
        Product = self.env['product.template']
        if rec.inventory_id:
            found = Product.search([('default_code', '=', rec.inventory_id)], limit=1)
            if found:
                return found
        return Product.browse()

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def _do_import(self):
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']


        imported = 0
        updated = 0
        error = 0

        # proses per reference number
        for reference_nbr in self.mapped('reference_nbr'):
            reference_lines = self.filtered(
                lambda l: l.reference_nbr == reference_nbr and l.import_state == 'pending'
            )
            if not reference_lines:
                continue

            first = reference_lines[0]

            try:
                product = self._find_existing_product(first)
                if not product:
                    raise UserError(
                        f'Product tidak ditemukan untuk InventoryID: '
                        f'{first.inventory_id or "-"}'
                    )
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(
                        f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}'
                    )

                dest_location = self._find_location_dest(first, warehouse)
                if not dest_location:
                    raise UserError(
                        f'Location tujuan tidak ditemukan untuk code: '
                        f'{first.location_dest_code or first.header_location_code or "-"}'
                    )

                origin = first.receipt_nbr or first.po_number or False

                vals = {
                    # row_number = fields.Integer(string='No', readonly=True)
                    # inventory_id = fields.Char(string='InventoryID', readonly=True)
                    # location = fields.Char(string='Location', readonly=True)
                    # requested_on = fields.Char(string='RequestedOn', readonly=True)
                    # revision = fields.Char(string='Revision', readonly=True)
                    # status = fields.Char(string='Status', readonly=True)
                    # type = fields.Char(string='Type', readonly=True)
                    # warehouse = fields.Char(string='Warehouse', readonly=True)
    

                    # Field standar Odoo
                    'name':line.description,
                    'product_quantity': float(line.quantity) if line.quantity else 0.0,
                    'code': line.reference_nbr or False,

                    # UOM
                    'uom_id': uom.id if uom else False,

                    # Field custom adt_
                    'adt_external_id': line.external_id or False,
                    'adt_reason_code': line.reason_code or False,
                    'adt_post_period': line.post_period or False,
                    'adt_location': line.location or False,
                    'adt_requested_on': line.requested_on or False,
                    'adt_revision': line.revision or False,
                    'adt_status': line.status or False,
                    'adt_warehouse': line.warehouse or False,
                    'adt_last_modified_datetime': self._parse_dt(line.last_modified_datetime),

                    # field custom, kalau ada di model
                }

                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Bom._fields}

                # pakai origin buat dedup
                bom = Bom.search([('origin', '=', origin)], limit=1)

                if bom:
                    if bom.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                        raise UserError(
                            f'Kit Assembly dengan Reference No {reference_nbr} sudah ada di Odoo dengan state '
                            f'{bom.state}, tidak bisa diupdate.'
                        )
                    bom.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    bom = Bom.create(vals)
                    action_state = 'imported'
                    imported += 1

                for line in reference_lines:
                    try:
                        product = self._find_existing_product(line)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.inventory_id or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        qty = self._parse_float(line.product_uom_qty)

                        # dedup move
                        move_domain = [('bom_id', '=', bom.id)]
                        if 'adt_line_external_id' in BomLine._fields and line.line_external_id:
                            move_domain.append(('adt_line_external_id', '=', line.line_external_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('product_uom_qty', '=', qty),
                            ]

                        existing_move = BomLine.search(move_domain, limit=1)
                        if existing_move:
                            line.write({
                                'import_state': action_state,
                                'import_message': f'Skip duplicate: {bom.name}',
                                'odoo_bom_id': bom.id,
                            })
                            continue

                        bom_line_vals = {
                            'bom_id': bom.id,
                            'product_id': product.id,
                            'product_qty': qty,
                            'product_uom_id': uom.id if uom else product.uom_id.id,

                            'adt_line_external_id': line.line_external_id or False,
                            'adt_line_note': line.line_note or False,
                            'adt_line_inventory_id': line.line_inventory_id or False,
                            'adt_line_nbr': line.line_nbr or False,
                            'adt_line_component_qty': line.line_component_qty or False,
                            'line_location_id': line.line_location_id or False,
                            'adt_line_quantity': line.line_quantity or False,
                            'adt_line_reason_code': line.line_reason_code or False,
                            'adt_stock_inventory_id': line.stock_inventory_id or False,
                            'adt_uom_code': line.uom_code or False,
                        }

                        # filter field yang ada di stock.move
                        bom_line_vals = {k: v for k, v in bom_line_vals.items() if k in BomLine._fields}

                        BomLine.create(bom_line_vals)

                        line.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {bom.name}',
                            'odoo_bom_id': bom.id,
                        })

                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        line.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_bom_id': bom.id if bom else False,
                        })
                        error += 1

            except Exception as e:
                _logger.exception("Error import receipt %s", reference_nbr)
                reference_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                error += len(reference_lines)

        msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Receipt',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_product(self):
        self.ensure_one()
        if not self.odoo_product_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id':    self.odoo_product_id.id,
            'view_mode': 'form',
        }
