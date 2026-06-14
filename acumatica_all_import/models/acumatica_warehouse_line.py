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
    is_active            = fields.Boolean(string='Aktif (Active)')
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
    odoo_warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse di Odoo', readonly=True, ondelete='set null')
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

    def bval(item, key):
        v = item.get(key, {})
        if isinstance(v, dict):
            return bool(v.get("value", False))
        return False

    def _find_existing_location(self, rec):
        """Cari warehouse code (BuildingID)."""
        location = self.env['stock.location.acumatica']
        if rec.warehouse_id:
            found = location.search([('code', '=', rec.warehouse_id)], limit=1)
            if found:
                return found
        return location.browse()
    
    def _search_warehouse(self, building):
        """Cari warehouse code (BuildingID)."""
        Warehouse = self.env['stock.warehouse']
        if building:
            found = Warehouse.search([('code', '=', building)], limit=1)
            if found:
                return found
        return Warehouse.browse()
    
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
                    'code':                    line.warehouse_id,
                    'building':                line.building_id,
                    'is_active':               self.bval(line.active),
                }

                existing = self._find_existing_location(line)
                if existing:
                    warehouse_odoo = self._search_warehouse(line.building_id)
                    if line.building_id and line.warehouse_id and warehouse_odoo:
                        vals.update({
                            'is_error': False,
                            'error_message': None
                        })
                        existing.write(vals)

                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Diupdate: {existing.name} (code: {existing.code})',
                        # 'odoo_warehouse_id': existing.id,
                    })
                    updated += 1
                else:
                    location_code = (line.warehouse_id or '').strip()
                    error_list = []
                    warehouse_odoo = self._search_warehouse(line.building_id)
                    if not location_code:
                        line.write({
                            'import_state': 'error',
                            'import_message': 'WarehouseID kosong, tidak bisa create location',
                        })
                        error += 1
                        vals['is_error'] = True
                        error_list.append('WarehouseID kosong')
                    if not line.building_id:
                        building_code = line.building_id.strip()
                        if not building_code:
                            line.write({
                                'import_state': 'error',
                                'import_message': 'BuildingID kosong',
                            })
                            error += 1
                            vals['is_error'] = True
                            error_list.append('BuildingID kosong')
                    if not warehouse_odoo:
                        line.write({
                            'import_state': 'error',
                            'import_message': f'Building {line.building_id} tidak ditemukan di Odoo, pastikan sudah dibuat sebagai warehouse sebelum mengimpor.',
                        })
                        error += 1
                        vals['is_error'] = True
                        error_list.append(f'Building {line.building_id} tidak ditemukan di Odoo')
                    new_location = self.env['stock.location.acumatica'].create(vals)
                    if error_list:
                        vals['error_message'] = '; '.join(error_list)
                        new_location.write({'is_error': True, 'error_message': vals['error_message']})
                    
                    if line.building_id:
                        wh_address = self.env['res.partner'].search([('name', '=', line.building_id)], limit=1)
                        if not wh_address:
                            company = self.env.user.commercial_partner_id
                            wh_address = self.env['res.partner'].create({'name': line.building_id, 'partner_type': 'warehouse', 'type': 'other', 'company_type': 'person', 'parent_id': company.id})
                        code = (line.building_id or '').strip().upper()
                        wh_building = self.env['stock.warehouse'].search([('code', '=', code)], limit=1)
                        if not wh_building:
                            wh_building = self.env['stock.warehouse'].create({'name': code, 'code': code, 'partner_id': wh_address.id, 'company_id': self.env.company.id,})

                    line.write({
                        'import_state':    'imported',
                        'import_message':  f'Dibuat: {new_location.name} (code: {new_location.code})',
                        # 'odoo_warehouse_id': new_location.id,
                    })
                    imported += 1

                # ── Import location lines ──
                # if odoo_wh and line.location_line_ids:
                #     line.location_line_ids._do_import(odoo_wh)

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
