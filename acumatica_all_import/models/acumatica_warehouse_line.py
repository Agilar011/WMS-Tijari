from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging

_logger = logging.getLogger(__name__)


class AcumaticaWarehouseLine(models.Model):
    """
    Tabel staging HEADER: data Warehouse dari Acumatica.

    Mapping:
      WarehouseID           → stock.warehouse.code      (Mandatory, sudah ada)
      Description           → stock.warehouse.name      (Mandatory, sudah ada)
      Active                → adt_state                 (Mandatory, to be)
      note                  → adt_note                  (Mandatory, to be)
      DropShipLocationID    → adt_drop_ship_location_id (Mandatory, to be)
      LastModifiedDateTime  → adt_last_modified_dt      (Mandatory, to be)
      ReceivingLocationID   → adt_receiving_location_id (Mandatory, to be)
      RMALocationID         → adt_rma_location_id       (Mandatory, to be)
      ShippingLocationID    → adt_shipping_location_id  (Mandatory, to be)
    """
    _name = 'acumatica.warehouse.line'
    _description = 'Data Warehouse dari Acumatica (Staging Header)'
    _order = 'row_number asc'
 
    # ─── Data dari Acumatica ─────────────────────────
    row_number           = fields.Integer(string='No', readonly=True)
    external_id          = fields.Char(string='UUID Acumatica', readonly=True)
    warehouse_id         = fields.Char(string='WarehouseID → code', readonly=True)
    description          = fields.Char(string='Description → name', readonly=True)
    active               = fields.Boolean(string='Active', readonly=True)
    note                 = fields.Text(string='Note', readonly=True)
    drop_ship_location_id = fields.Char(string='DropShipLocationID', readonly=True)
    last_modified_dt     = fields.Char(string='LastModifiedDateTime', readonly=True)
    receiving_location_id = fields.Char(string='ReceivingLocationID', readonly=True)
    rma_location_id      = fields.Char(string='RMALocationID', readonly=True)
    shipping_location_id = fields.Char(string='ShippingLocationID', readonly=True)
    building_id          = fields.Char(string='BuildingID', readonly=True)

    # ─── Detail locations (one2many) ─────────────────
    location_line_ids = fields.One2many(
        'acumatica.warehouse.location.line',
        'warehouse_line_id',
        string='Locations',
        readonly=True,
    )
    location_count = fields.Integer(
        string='Jumlah Lokasi',
        compute='_compute_location_count',
        store=True,
    )

    @api.depends('location_line_ids')
    def _compute_location_count(self):
        for rec in self:
            rec.location_count = len(rec.location_line_ids)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message    = fields.Char(string='Keterangan', readonly=True)
    odoo_warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse di Odoo', readonly=True)
    selected          = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one(
        'acumatica.warehouse.config',
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

    def _find_existing_warehouse(self, rec):
        """Cari warehouse code (BuildingID)."""
        WH = self.env['stock.warehouse']
        # if rec.external_id:
        #     found = WH.search([('adt_external_id', '=', rec.external_id)], limit=1)
        #     if found:
        #         return found
        if rec.building_id:
            found = WH.search([('code', '=', rec.building_id)], limit=1)
            if found:
                return found
        return WH.browse()
    
    def _find_existing_warehouse_location(self, rec):
        """Cari warehouse location by code (WarehouseID)."""
        WH = self.env['stock.location']
        # if rec.external_id:
        #     found = WH.search([('adt_external_id', '=', rec.external_id)], limit=1)
        #     if found:
        #         return found
        if rec.warehouse_id:
            found = WH.search([('name', '=', rec.warehouse_id)], limit=1)
            if found:
                return found
        return WH.browse()

    # ─── Actions ─────────────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def _do_import(self):
        """
        Import warehouse header ke stock.warehouse,
        lalu trigger import semua location line-nya.


        Import ini bakal ngebuat stock.warehouse berdasarkan building_id,
        kalo ternyata udah ada wareshouse, nanti fungsi ini bakal ngebuat location dengan parent warehouse berdasarkan building_id.
        EXAMPLE: line.warehouse_id = WH33-FG & line.building_id = WH33, kalo WH33 udah ada, maka akan dibuat location WH33-FG dengan parent location WH33/Stock.
        """
        imported = updated = error = 0

        for line in self:
            try:
                if not line.warehouse_id or not line.description:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'WarehouseID atau Description kosong',
                    })
                    error += 1
                    continue

                vals = {
                    'name':                    line.description,
                    # 'code':                    line.warehouse_id,
                    # 'adt_external_id':         line.external_id or False,
                    # 'adt_note':                line.note or False,
                    # 'adt_state':               line.active,
                    # 'adt_drop_ship_location_id': line.drop_ship_location_id or False,
                    # 'adt_last_modified_dt':    self._parse_dt(line.last_modified_dt),
                    # 'adt_receiving_location_id': line.receiving_location_id or False,
                    # 'adt_rma_location_id':     line.rma_location_id or False,
                    # 'adt_shipping_location_id': line.shipping_location_id or False,
                }

                existing = self._find_existing_warehouse(line)
                if existing:
                    location_existing = self.env['stock.location'].search([
                        ('name', '=', line.warehouse_id),
                    ], limit=1)

                    if location_existing:
                        line.write({
                            'import_state': 'updated',
                            'import_message': f'Location sudah ada: {location_existing.display_name}',
                            'odoo_warehouse_id': existing.id,
                        })
                        updated += 1
                        continue

                    else:
                        new_wh_location = self.env['stock.location'].create({
                            **vals,
                            'location_id': existing.lot_stock_id.id if existing.lot_stock_id else False,
                            'usage': 'view',
                        })
                    odoo_wh = new_wh_location
                    # existing.write(vals)
                    # odoo_wh = existing
                    # line.write({
                    #     'import_state':    'updated',
                    #     'import_message':  f'Diupdate: {existing.name} (code: {existing.code})',
                    #     'odoo_warehouse_id': existing.id,
                    # })
                    # updated += 1
                else:
                    # new_wh = self.env['stock.warehouse'].create(vals)
                    building_code = (line.building_id or '').strip()
                    location_code = (line.warehouse_id or '').strip()

                    if not building_code:
                        line.write({
                            'import_state': 'error',
                            'import_message': 'BuildingID kosong, tidak bisa create warehouse',
                        })
                        error += 1
                        continue
                    new_wh = self.env['stock.warehouse'].create({
                        'name': line.building_id,
                        'code': line.building_id
                    })
                    new_wh_location = self.env['stock.location'].create({
                        **vals,
                        'location_id': new_wh.lot_stock_id.id if new_wh.lot_stock_id else False,
                        'usage': 'view',
                    })
                    odoo_wh = new_wh_location
                    line.write({
                        'import_state':    'imported',
                        'import_message':  f'Dibuat: {new_wh.name} (code: {new_wh.code})',
                        'odoo_warehouse_id': new_wh.id,
                    })
                    imported += 1

                # ── Import location lines ──
                if odoo_wh and line.location_line_ids:
                    line.location_line_ids._do_import(odoo_wh)

            except Exception as e:
                _logger.error("Error import Warehouse %s: %s", line.warehouse_id, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Warehouse',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_view_locations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Locations - {self.warehouse_id}',
            'res_model': 'acumatica.warehouse.location.line',
            'view_mode': 'list,form',
            'domain': [('warehouse_line_id', '=', self.id)],
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_warehouse(self):
        self.ensure_one()
        if not self.odoo_warehouse_id:
            raise UserError('Belum diimport.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.warehouse',
            'res_id': self.odoo_warehouse_id.id,
            'view_mode': 'form',
        }
