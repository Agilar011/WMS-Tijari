from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AcumaticaUomLine(models.Model):
    """
    Tabel staging: hasil tarikan data UoM dari Acumatica
    Mapping:
      - UnitID     → uom.category (nama kategori)
      - Description → uom.uom (nama satuan)
    """
    _name = 'acumatica.uom.line'
    _description = 'Data UoM dari Acumatica (Staging)'
    _order = 'row_number asc, unit_id asc'

    # ─── Data dari Acumatica ─────────────────────────
    row_number  = fields.Integer(string='No', readonly=True)
    unit_id     = fields.Char(string='UnitID (→ Kategori)', required=True, readonly=True)
    description = fields.Char(string='Description (→ Nama UoM)', readonly=True)
    external_id = fields.Char(string='UUID Acumatica', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('skipped',  'Dilewati (Sudah Ada)'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message  = fields.Char(string='Keterangan', readonly=True)
    odoo_uom_id     = fields.Many2one('uom.uom', string='UoM di Odoo', readonly=True)
    odoo_categ_id   = fields.Many2one('uom.category', string='Kategori di Odoo', readonly=True)
    selected        = fields.Boolean(string='Pilih', default=True)

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # ─── Computed: sudah ada di Odoo? ────────────────
    exists_in_odoo = fields.Boolean(
        string='Sudah Ada di Odoo',
        compute='_compute_exists_in_odoo',
        store=False,
    )

    @api.depends('description')
    def _compute_exists_in_odoo(self):
        for rec in self:
            if rec.description:
                existing = self.env['uom.uom'].search([
                    ('name', '=ilike', rec.description)
                ], limit=1)
                rec.exists_in_odoo = bool(existing)
            else:
                rec.exists_in_odoo = False

    # ─── Action: Import baris yang dipilih ───────────
    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        """Import 1 baris saja (dari tombol di list)"""
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        """
        Logika import:
          - UnitID     → cari/buat uom.category
          - Description → cari/buat uom.uom di dalam kategori tersebut
        """
        imported = skipped = error = 0

        for line in self:
            try:
                if not line.description:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'Description kosong, tidak bisa jadi nama UoM',
                    })
                    error += 1
                    continue

                # ── 1. Cari Kategori Unit ──
                uom_categ = self.env['uom.category'].search([
                    ('name', '=ilike', 'Unit')
                ], limit=1)
                if not uom_categ:
                    uom_categ = self.env['uom.category'].create({'name': 'Unit'})
                    _logger.info("Kategori UoM baru dibuat: %s", 'Unit')

                # ── 2. Cek apakah uom.uom (Description) sudah ada ──
                existing = self.env['uom.uom'].search([
                    ('name', '=ilike', line.description),
                    ('category_id', '=', uom_categ.id),
                ], limit=1)

                if existing:
                    existing.categ_id = uom_categ.id  # Pastikan kategorinya sesuai
                    line.write({
                        'import_state':   'skipped',
                        'import_message': f'Sudah ada: {existing.name} (kategori: {uom_categ.name})',
                        'odoo_uom_id':    existing.id,
                        'odoo_categ_id':  uom_categ.id,
                    })
                    skipped += 1
                else:
                    # Cek apakah kategori sudah punya reference unit
                    has_reference = self.env['uom.uom'].search([
                        ('category_id', '=', uom_categ.id),
                        ('uom_type', '=', 'reference'),
                    ], limit=1)

                    # ── 3. Buat uom.uom baru ──
                    new_uom = self.env['uom.uom'].create({
                        'name':        line.description,
                        'category_id': uom_categ.id,
                        'uom_type':    'smaller' if has_reference else 'reference',
                        'factor':      1.0,
                        'rounding':    0.01,
                        'active':      True,
                    })
                    line.write({
                        'import_state':   'imported',
                        'import_message': f'Dibuat: {new_uom.name} → kategori: {uom_categ.name}',
                        'odoo_uom_id':    new_uom.id,
                        'odoo_categ_id':  uom_categ.id,
                    })
                    imported += 1

            except Exception as e:
                _logger.error("Error import UoM line %s / %s: %s", line.unit_id, line.description, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        # Notifikasi hasil
        msg = f'Import selesai: {imported} berhasil, {skipped} dilewati, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import UoM',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Action: Reset status ─────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state in ('skipped', 'error')).write({
            'import_state': 'pending',
            'import_message': False,
        })

    # ─── Select / Deselect all ───────────────────────
    def action_select_all(self):
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})
