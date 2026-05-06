from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AcumaticaWarehouseLocationLine(models.Model):
    """
    Tabel staging DETAIL: data Locations dari Acumatica (child dari Warehouse).

    Mapping:
      LocationID    → stock.location.name       (Mandatory, sudah ada)
      Description   → adt_description           (Mandatory, to be)
      Active        → adt_state                 (Mandatory, to be)
      note          → adt_note                  (Mandatory, to be)
    """
    _name = 'acumatica.warehouse.location.line'
    _description = 'Data Location dari Acumatica (Staging Detail)'
    _order = 'row_number asc'

    warehouse_line_id = fields.Many2one(
        'acumatica.warehouse.line',
        string='Warehouse',
        readonly=True,
        ondelete='cascade',
        required=True,
    )

    # ─── Data dari Acumatica ─────────────────────────
    row_number   = fields.Integer(string='No', readonly=True)
    external_id  = fields.Char(string='UUID Acumatica', readonly=True)
    location_id  = fields.Char(string='LocationID → name', readonly=True)
    description  = fields.Char(string='Description → adt_description', readonly=True)
    active       = fields.Boolean(string='Active', readonly=True)
    note         = fields.Text(string='Note → adt_note', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message     = fields.Char(string='Keterangan', readonly=True)
    odoo_location_id   = fields.Many2one('stock.location', string='Location di Odoo', readonly=True)

    # ─── Import Logic ────────────────────────────────
    def _find_existing_location(self, rec, parent_location):
        """Cari location by UUID dulu, lalu by name + parent."""
        Loc = self.env['stock.location']
        if rec.external_id:
            found = Loc.search([('adt_external_id', '=', rec.external_id)], limit=1)
            if found:
                return found
        if rec.location_id and parent_location:
            found = Loc.search([
                ('name', '=', rec.location_id),
                ('location_id', '=', parent_location.id),
            ], limit=1)
            if found:
                return found
        return Loc.browse()

    def _do_import(self, odoo_warehouse):
        """
        Import location lines ke stock.location.
        Parent location = lot_stock_id dari warehouse (lokasi internal utama).
        dipanggil oleh warehouse line setelah warehouse berhasil dibuat/diupdate.
        """
        # Parent = lot_stock_id warehouse (misal WH/Stock)
        parent_location = odoo_warehouse.lot_stock_id
        if not parent_location:
            parent_location = self.env['stock.location'].search([
                ('warehouse_id', '=', odoo_warehouse.id),
                ('usage', '=', 'internal'),
            ], limit=1)

        for line in self:
            try:
                if not line.location_id:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'LocationID kosong',
                    })
                    continue

                vals = {
                    'name':             line.location_id,
                    'usage':            'internal',
                    'location_id':      parent_location.id if parent_location else False,
                    'active':           line.active,
                    'adt_external_id':  line.external_id or False,
                    'adt_note':         line.note or False,
                    'adt_state':        line.active,
                    'adt_description':  line.description or False,
                    'adt_location_id':  line.location_id or False,
                }

                existing = self._find_existing_location(line, parent_location)

                if existing:
                    existing.write(vals)
                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Diupdate: {existing.complete_name}',
                        'odoo_location_id': existing.id,
                    })
                else:
                    new_loc = self.env['stock.location'].create(vals)
                    line.write({
                        'import_state':    'imported',
                        'import_message':  f'Dibuat: {new_loc.complete_name}',
                        'odoo_location_id': new_loc.id,
                    })

            except Exception as e:
                _logger.error("Error import Location %s: %s", line.location_id, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })

    def action_open_location(self):
        self.ensure_one()
        if not self.odoo_location_id:
            raise UserError('Belum diimport.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.location',
            'res_id': self.odoo_location_id.id,
            'view_mode': 'form',
        }
