from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from markupsafe import Markup, escape
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
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Warehouse dari Acumatica (Staging Header)'
    _order = 'row_number asc'
 
    # ─── Data dari Acumatica ─────────────────────────
    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Acumatica', readonly=True)
    warehouse_id = fields.Char(string='WarehouseID → code', readonly=True)
    description = fields.Char(string='Description → name', readonly=True)
    active = fields.Boolean(string='Active', readonly=True)
    is_active = fields.Boolean(string='Aktif (Active)')
    note = fields.Text(string='Note', readonly=True)
    drop_ship_location_id = fields.Char(string='DropShipLocationID', readonly=True)
    last_modified_dt = fields.Char(string='LastModifiedDateTime', readonly=True)
    receiving_location_id = fields.Char(string='ReceivingLocationID', readonly=True)
    rma_location_id = fields.Char(string='RMALocationID', readonly=True)
    shipping_location_id = fields.Char(string='ShippingLocationID', readonly=True)
    building_id = fields.Char(string='BuildingID', readonly=True)

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True)

    import_message = fields.Char(string='Generation Message', readonly=True)
    odoo_warehouse_id = fields.Many2one('stock.warehouse', string='Document Reference', readonly=True, ondelete='set null')
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    config_id = fields.Many2one(
        'acumatica.config',
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


    def _find_existing_location(self, rec):
        """Cari warehouse code (WarehouseID)."""
        location = self.env['stock.location.acumatica']
        found = False
        if rec.warehouse_id:
            found = location.search([('code', '=', rec.warehouse_id)], limit=1)
        return found

    def _find_existing_location_cons(self, rec):
        """Cari warehouse code (WarehouseID)."""
        location = self.env['stock.location']
        found = False
        if rec.warehouse_id:
            found = location.search([('name', '=', rec.warehouse_id)], limit=1)

        return found

    def _search_warehouse(self, building):
        """Cari warehouse code (BuildingID)."""
        Warehouse = self.env['stock.warehouse']
        if building:
            found = Warehouse.search([('code', '=', building)], limit=1)
            if found:
                return found
        return Warehouse.browse()

    def _get_virtual_locations_parent(self):
        parent = self.env.ref('stock.stock_location_locations_virtual', raise_if_not_found=False)
        if parent:
            return parent
        return self.env['stock.location'].search([
            ('name', '=', 'Virtual Locations'),
            ('usage', '=', 'view'),
        ], limit=1)

    def _find_virtual_location_for_building(self, building_id):
        building_code = (building_id or '').strip().upper()
        if not building_code or building_code == 'WH33':
            return self.env['stock.location'].browse()

        parent = self._get_virtual_locations_parent()
        if not parent:
            return self.env['stock.location'].browse()

        return self.env['stock.location'].sudo().search([
            ('name', '=', building_code),
            ('location_id', '=', parent.id),
        ], limit=1)

    def _create_virtual_location_for_building(self, building_id):
        building_code = (building_id or '').strip().upper()
        if not building_code or building_code == 'WH33':
            return self.env['stock.location'].browse()

        parent = self._get_virtual_locations_parent()
        if not parent:
            raise UserError('Parent location "Virtual Locations" tidak ditemukan.')

        virtual_location = self._find_virtual_location_for_building(building_code)
        if virtual_location:
            return virtual_location

        return self.env['stock.location'].sudo().create({
            'name': building_code,
            'location_id': parent.id,
            'usage': 'inventory',
            'company_id': False,
        })

    def _generate_virtual_locations_for_existing_buildings(self):
        buildings = set(
            building.strip().upper()
            for building in self.search([('building_id', '!=', False)]).mapped('building_id')
            if building and building.strip()
        )
        buildings.update(
            building.strip().upper()
            for building in self.env['stock.location.acumatica'].sudo().search([
                ('building', '!=', False),
            ]).mapped('building')
            if building and building.strip()
        )

        locations = self.env['stock.location'].browse()
        for building in sorted(buildings):
            location = self._create_virtual_location_for_building(building)
            if location:
                locations |= location
        return locations
    
    # ─── Actions ─────────────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def _create_partner(self, line):
        Partner = self.env['res.partner']
        wh_address = Partner.search([('name', '=', line.building_id)], limit=1)
        if not wh_address:
            company = self.env.company.partner_id
            wh_address = Partner.create({
                'name': line.building_id,
                'partner_type': 'warehouse',
                'type': 'other',
                'company_type': 'person',
                'parent_id': company.id
            })

        return wh_address or False


    def _create_warehouse(self, line, address):
        Warehouse = self.env['stock.warehouse']
        code = (line.building_id or '').strip().upper()
        wh_building = Warehouse.search([('code', '=', code)], limit=1)
        if not wh_building:
            wh_building = Warehouse.create({
                'name': code,
                'code': code,
                'partner_id': address.id,
                'company_id': self.env.company.id,
                'reception_steps': 'two_steps',
                'delivery_steps': 'pick_pack_ship',
            })

        return wh_building or False

    def _receiving_location_is_consignment(self, line):
        return (line.receiving_location_id or '').strip().upper() == 'CONS'

    def _get_or_create_consignment_locations(self, line, warehouse=False):
        building_code = (line.building_id or '').strip().upper()
        warehouse_code = (line.warehouse_id or '').strip().upper()
        if (
            not building_code
            or not warehouse_code
            or not line.is_active
            or not self._receiving_location_is_consignment(line)
        ):
            return self.env['stock.location'].browse()

        warehouse = warehouse or self._search_warehouse(building_code)
        if not warehouse:
            wh_address = self._create_partner(line)
            if wh_address:
                warehouse = self._create_warehouse(line, wh_address)
        if not warehouse:
            return self.env['stock.location'].browse()

        Location = self.env['stock.location'].sudo()

        def get_or_create_child(parent, name, is_consignment=False):
            location = Location.search([
                ('location_id', '=', parent.id),
                ('name', '=', name),
            ], limit=1)
            has_consignment_field = 'is_consignment' in Location._fields
            if location:
                if is_consignment and has_consignment_field and not location.is_consignment:
                    location.write({'is_consignment': True})
                return location

            vals = {
                'name': name,
                'usage': 'internal',
                'location_id': parent.id,
            }
            if warehouse.company_id:
                vals['company_id'] = warehouse.company_id.id
            if has_consignment_field:
                vals['is_consignment'] = is_consignment
            return Location.create(vals)

        cons_root = get_or_create_child(warehouse.view_location_id, 'CONS')
        return get_or_create_child(cons_root, warehouse_code, is_consignment=True)

    def _handle_acumatica_error(self, err_msg=False):
        AcumaticaError = self.env['acumatica.error.master']
        acumatica_err_id = self.acumatica_err_id
        if not err_msg:
            if acumatica_err_id:
                acumatica_err_id.import_state = 'solved'
                return
            return

        state = 'error'
        if not acumatica_err_id:
            acumatica_err_id = AcumaticaError.create({
                'name': f'Warehouse-{self.id}',
                'data_type': 'warehouse',
                'import_state': state,
                'data_id': self.id,
                'error_msg': err_msg
            })
            self.acumatica_err_id = acumatica_err_id

        acumatica_err_id.import_state = state
        acumatica_err_id.error_msg = err_msg

    def _search_parent_consignment_location(self, warehouse_view_location):
        location = False
        location = self.env['stock.location'].search([
            ('name', '=', 'CONS'),
            ('location_id', '=', warehouse_view_location.id),
        ], limit=1)
        return location

    def _create_parent_consignment_location(self, location, warehouse_odoo):
        vals = {
            'name': 'CONS',
            'usage': 'internal',
            'location_id': warehouse_odoo.view_location_id.id,
        }
        return self.env['stock.location'].create(vals)

    def _create_location_consignment(self, line, warehouse_odoo):
        """Backward-compatible wrapper for the canonical CONS hierarchy."""
        return self._get_or_create_consignment_locations(line, warehouse_odoo)


    def _do_import(self):
        """
        Import warehouse header ke stock.warehouse,
        lalu trigger import semua location line-nya.


        Import ini bakal ngebuat stock.warehouse berdasarkan building_id,
        kalo ternyata udah ada wareshouse, nanti fungsi ini bakal ngebuat location dengan parent warehouse berdasarkan building_id.
        EXAMPLE: line.warehouse_id = WH33-FG & line.building_id = WH33, kalo WH33 udah ada, maka akan dibuat location WH33-FG dengan parent location WH33/Stock.
        """
        created = updated = error = 0

        for line in self:
            try:
                if not line.warehouse_id or not line.description:

                    err_msg = 'WarehouseID atau Description kosong'
                    line.write({
                        'import_state': 'error',
                        'import_message': err_msg,
                    })

                    line._handle_acumatica_error(err_msg)

                    line._log_import_result(
                        'error',
                        f'Gagal mengimpor data: {err_msg}',
                        False,
                        False
                    )
                    error += 1
                    continue

                vals = {
                    'name': line.description,
                    'code': line.warehouse_id,
                    'building': line.building_id,
                    'is_active': bool(line.building_id),
                }

                if line.building_id and not self._find_virtual_location_for_building(line.building_id):
                    self._generate_virtual_locations_for_existing_buildings()

                cons = self._receiving_location_is_consignment(line)
                existing = self._find_existing_location(line)
                if existing and not cons:


                    warehouse_odoo = self._search_warehouse(line.building_id)
                    # if (
                    #     line.building_id
                    #     and line.is_active
                    #     and not warehouse_odoo
                    #     and self._receiving_location_is_consignment(line)
                    # ):
                    #     wh_address = self._create_partner(line)
                    #     if wh_address:
                    #         warehouse_odoo = self._create_warehouse(line, wh_address)
                    if line.building_id and line.warehouse_id and warehouse_odoo:
                        vals.update({
                            'is_error': False,
                            'error_message': None,
                            'odoo_building_id': warehouse_odoo.id,
                        })
                    elif not line.building_id:
                        vals.update({
                            'is_error': True,
                            'error_message': 'BuildingID kosong',
                        })
                    else:
                        vals.update({
                            'is_error': True,
                            'error_message': (
                                'BuildingID %s belum ditemukan di Odoo.'
                                % line.building_id
                            ),
                        })

                    # Tetap update mapping lama berdasarkan WarehouseID. Ini penting
                    # ketika fetch pertama BuildingID kosong lalu fetch berikutnya
                    # sudah membawa BuildingID.
                    changed_fields = line._get_changed_fields(
                        existing,
                        vals,
                    )
                    existing.write(vals)

                    line._log_import_result(
                        'updated',
                        f'Data {existing.display_name} berhasil diperbarui.',
                        existing,
                        changed_fields,
                    )

                    if not existing.is_error:
                        line._handle_acumatica_error()

                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Updated: {existing.name} (code: {existing.code})',
                        'odoo_warehouse_id': warehouse_odoo.id if warehouse_odoo else None,
                    })
                    updated += 1
                else:
                    location_code = (line.warehouse_id or '').strip()
                    error_list = []
                    wh_builidng = self.env['stock.warehouse'].browse()
                    warehouse_odoo = self._search_warehouse(line.building_id)
                    if not location_code:

                        err_msg = "WarehouseID kosong, tidak bisa create location"
                        line.write({
                            'import_state': 'error',
                            'import_message': err_msg,
                        })

                        line._handle_acumatica_error(err_msg)

                        line._log_import_result(
                            'error',
                            f'Gagal mengimpor data: {err_msg}',
                            False,
                            False
                        )
                        error += 1
                        vals['is_error'] = True
                        error_list.append(err_msg)
                    if not line.building_id:
                        building_code = ''
                        if not building_code:

                            err_msg = "BuildingID kosong"
                            line.write({
                                'import_state': 'error',
                                'import_message': err_msg,
                            })

                            line._handle_acumatica_error(err_msg)

                            line._log_import_result(
                                'error',
                                f'Gagal mengimpor data: {err_msg}',
                                False,
                                False
                            )
                            error += 1
                            vals['is_error'] = True
                            error_list.append(err_msg)

                    if self._receiving_location_is_consignment(line) and line.building_id and line.warehouse_id and line.is_active:
                        if not warehouse_odoo:
                            raise UserError(
                                'Warehouse BuildingID %s belum ditemukan untuk lokasi consignment.'
                                % line.building_id
                            )

                        cons_location = self._create_location_consignment(line, warehouse_odoo)
                        line.write({
                            'import_state': 'created',
                            'import_message': (
                                'Location consignment siap: %s'
                                % cons_location.complete_name
                            ),
                            'odoo_warehouse_id': warehouse_odoo.id,
                        })
                        line._handle_acumatica_error()
                        line._log_import_result(
                            'created',
                            'Location consignment %s berhasil disiapkan.'
                            % cons_location.display_name,
                            cons_location,
                            False,
                        )
                        created += 1
                        continue
                        
                    new_location = self.env['stock.location.acumatica'].create(vals)
                    if error_list:
                        new_location.write({
                            'is_error': True, 
                            'error_message': '; '.join(error_list)
                        })
                    
                    if line.building_id:
                        wh_address = self._create_partner(line)
                        if wh_address: 
                            wh_builidng = self._create_warehouse(line, wh_address)
                        if wh_builidng:
                            new_location.write({
                                'is_error': False,
                                'odoo_building_id': wh_builidng.id
                            })
                            # self._get_or_create_consignment_locations(line, wh_builidng)

                    line.write({
                        'import_state':    'created',
                        'import_message':  f'Dibuat: {new_location.name} (code: {new_location.code})',
                        'odoo_warehouse_id': wh_builidng.id if wh_builidng else None,
                    })

                    line._handle_acumatica_error()

                    line._log_import_result(
                        'created',
                        f'Data {new_location.name} (code: {new_location.code}) berhasil dibuat.',
                        new_location,
                        False
                    )
                    created += 1

            except Exception as e:
                _logger.error("Error import Warehouse %s: %s", line.warehouse_id, str(e))

                err_msg = str(e)[:200]
                line.write({
                    'import_state':   'error',
                    'import_message': err_msg,
                })

                line._handle_acumatica_error(err_msg)

                line._log_import_result(
                    'error',
                    f'Gagal mengimpor data: {err_msg}',
                    False,
                    False
                )
                error += 1
                raise

        msg = f'Import selesai: {created} dibuat, {updated} diupdate, {error} error.'
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
            'res_model': 'stock.location.acumatica',
            'view_mode': 'list,form',
            'domain': [('code', '=', self.warehouse_id)],
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'staged',
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

    def _get_changed_fields(self, record, vals):
        changed_fields = []

        for field_name, new_value in vals.items():
            field = record._fields.get(field_name)

            if not field:
                continue

            old_value = record[field_name]

            # Normalisasi nilai
            old_value = old_value or False
            new_value = new_value or False

            if old_value != new_value:
                changed_fields.append({
                    'field_name': field_name,
                    'field_label': field.string,
                    'old_value': old_value,
                    'new_value': new_value,
                })

        return changed_fields
        
    def _log_import_result(
        self,
        state,
        message,
        record=False,
        changed_fields=None,
    ):
        titles = {
            'created': '✅ Import Berhasil',
            'updated': '🔄 Data Diperbarui',
            'error': '❌ Import Gagal',
        }

        body = Markup("""
            <p>
                <strong>{}</strong>
            </p>
            <p>{}</p>
        """).format(
            titles.get(state, 'Import Log'),
            message,
        )

        if changed_fields:
            body += Markup("""
                <p><strong>Perubahan:</strong></p>
                <ul>
            """)

            for change in changed_fields:
                old_value = change['old_value'] or '-'
                new_value = change['new_value'] or '-'

                body += Markup("""
                    <li>
                        <strong>{}</strong>:
                        {} → {}
                    </li>
                """).format(
                    escape(change['field_label']),
                    escape(str(old_value)),
                    escape(str(new_value)),
                )

            body += Markup("</ul>")

        if record:
            body += Markup("""
                <p>
                    Record Location Acumatica:
                    <a href="#"
                    data-oe-model="{}"
                    data-oe-id="{}">
                        {} code ({})
                    </a>
                </p>
            """).format(
                escape(record._name),
                record.id,
                escape(record.display_name),
                escape(record.code),
            )

        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
