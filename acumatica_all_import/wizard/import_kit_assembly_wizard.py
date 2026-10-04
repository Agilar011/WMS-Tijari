from odoo import models, fields
from odoo.exceptions import UserError
import logging

from psycopg2 import IntegrityError

_logger = logging.getLogger(__name__)


class ImportKitAssemblyWizard(models.TransientModel):
    _name        = 'import.kit.assembly.wizard'
    _description = 'Wizard Import Kit Assembly dari Acumatica'

    # =========================
    # INPUT
    # =========================
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )

    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=5000)
    batch_size = fields.Integer(string='Batch Size untuk Fetch', default=100)

    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0)

    total_target = fields.Integer(
        string='Total Data Diambil',
        help='Kosongkan untuk ambil semua data'
    )

    # =========================
    # STATE
    # =========================
    state = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    # =========================
    # SUMMARY
    # =========================
    total_fetched  = fields.Integer(string='Total Data Ditarik', readonly=True)
    total_new      = fields.Integer(string='Item Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    # =========================
    # FETCH
    # =========================
    def action_fetch_data(self):
        print("==========================================================================================")
        print("ACTION: Fetch Wizard data from Acumatica")
        print("==========================================================================================")
        # print("Starting data fetch...")
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # =========================
        # FETCH (AUTO LOOP)
        # =========================
        import math

        effective_total = self.total_target or self.fetch_limit
        if effective_total <= 0:
            raise UserError('Maks Data Ditarik harus lebih besar dari 0.')
        if self.batch_size <= 0:
            raise UserError('Batch Size untuk Fetch harus lebih besar dari 0.')

        raw_list = []
        loop_count = math.ceil(effective_total / self.batch_size)

        batch_data = self.fetch_kit_assembly_data(
            limit=self.batch_size,
        )
        if not batch_data:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Bom = self.env['mrp.bom']

        new_count = existing_count = 0
        lines_to_create = []

        for item in raw_list:
            reference_nbr = item.get('reference_nbr') or ''
            existing_bom = Bom.browse()
            if reference_nbr:
                existing_bom = Bom.search([('code', '=', reference_nbr)], limit=1)

            if existing_bom:
                existing_count += 1
                msg = f'Sudah ada → akan diupdate: {existing_bom.display_name}'
            else:
                new_count += 1
                msg = ''

            lines_to_create.append({
                'config_id': self.config_id.id,

                # Header fields
                'row_number': item.get('row_number') or 0,
                'external_id': item.get('external_id') or '',
                'inventory_id': item.get('inventory_id') or '',
                'description': item.get('description') or '',
                'last_modified_datetime': item.get('last_modified_datetime') or '',
                'location': item.get('location') or '',
                'BuildingID': item.get('building_id') or item.get('BuildingID') or '',
                'note_header': item.get('note_header') or '',
                'note_header_id': item.get('note_header_id') or '',
                'post_period': item.get('post_period') or '',
                'date': item.get('date') or '',
                'quantity': item.get('quantity') or '',
                'reason_code': item.get('reason_code') or '',
                'reference_nbr': reference_nbr,
                'requested_on': item.get('requested_on') or '',
                'revision': item.get('revision') or '',
                'status': item.get('status') or '',
                'type': item.get('type') or '',
                'uom': item.get('uom') or '',
                'warehouse': item.get('warehouse') or '',

                # Line fields
                'line_external_id': item.get('line_external_id') or '',
                'line_note': item.get('line_note') or '',
                'line_note_id': item.get('line_note_id') or '',
                'line_inventory_id': item.get('line_inventory_id') or '',
                'line_component_qty': item.get('line_component_qty') or '',
                'line_nbr': item.get('line_nbr') or '',
                'line_location_id': item.get('line_location_id') or '',
                'line_quantity': item.get('line_quantity') or '',
                'line_reason_code': item.get('line_reason_code') or '',
                'stock_inventory_id': item.get('stock_inventory_id') or '',
                'line_uom': item.get('line_uom') or '',

                # Import flags
                'import_state': 'staged',
                'import_message': msg,
                'odoo_bom_id': existing_bom.id if existing_bom else False,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })

        changed_reference_nbrs = {
            vals['reference_nbr']
            for vals in lines_to_create
            if vals.get('reference_nbr')
        }
        if changed_reference_nbrs:
            self.env['acumatica.kit.assembly.line'].search([
                ('config_id', '=', self.config_id.id),
                ('reference_nbr', 'in', list(changed_reference_nbrs)),
            ]).unlink()
        self.env['acumatica.kit.assembly.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.kit.assembly.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    # =========================
    # VIEW STAGING
    # =========================

    def fetch_kit_assembly_data(self, limit=100):
        """Fetch 1 page Kit Assembly dari Acumatica (paging via $top/$skip)."""
        # print("==========================================================================================")
        # print("ACTION: Fetch data from Acumatica")
        # print("==========================================================================================")

        self.ensure_one()
        session = self.config_id._do_login()
        staging_header = self.env['acumatica.kit.assembly']
        staging_line = self.env['acumatica.kit.assembly.component']

        AcumaticaErrorService = self.env["acumatica.webhook.error.service"]
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            # print(f"Fetching Kit Assembly data from {endpoint} with limit={limit} and offset={offset}...")
            params = {
                '$top': limit,
                '$expand': self.config_id.odata_expand
            }
            body = {
                "BuildingID": {
                    "value": ""
                }
            }

            response = session.put(endpoint, params=params, json=body, timeout=300)
            if response.status_code != 200:

                last_error = (
                    f'Gagal fetch data Kit Assembly '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

                AcumaticaErrorService.send_error(
                    webhook_type="fetch",
                    webhook_name="issue change item",
                    error=last_error,
                    error_type="http",
                )
                
                raise UserError(last_error)

            payload = response.json()
            # Acumatica can return the GI rows under the named root key
            # instead of the generic ``value``/``rows`` envelope.
            raw_data = []
            if isinstance(payload, dict) and 'KitAssemblyGIDetails' in payload:
                details = payload.get('KitAssemblyGIDetails')
                if isinstance(details, list):
                    raw_data = details
                elif isinstance(details, dict):
                    raw_data = details.get('value') or details.get('rows') or []
            if not raw_data:
                raw_data = self.config_id._normalize_rows(payload)
            raw_data = [item for item in raw_data if isinstance(item, dict)]
            result = []
            assemblies_by_reference = {}
            components_seen_by_reference = {}
            empty_headers_seen = set()

            for item_index, item in enumerate(raw_data):

                last_modified_datetime = self._val(item, 'LastModifiedDateTime')
                print(f"Last Modified Date Time: :{last_modified_datetime}")
                print(self._val(item, 'Warehouse'))
                header = {
                    'name': self._val(item, 'ReferenceNbr'),
                    'external_id': item.get('id', '') or '',
                    'row_number': item.get('rowNumber', 0) or 0,
                    'description': self._val(item, 'Description'),
                    'inventory_id': self._val(item, 'InventoryID'),
                    'last_modified_datetime': last_modified_datetime,
                    'location': self._val(item, 'Location'),
                    'building_id': self._val(item, 'BuildingID'),
                    'note_header': self._val(item, 'NoteHeader'),
                    'note_header_id': self._val(item, 'NoteHeaderID'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'date': self._val(item, 'Date'),
                    'quantity': self._val(item, 'Qty'),
                    'reason_code': self._val(item, 'ReasonCode'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'requested_on': self._val(item, 'RequestedOn'),
                    'revision': self._val(item, 'Revision'),
                    'status': self._val(item, 'Status'),
                    'type': self._val(item, 'Type'),
                    'uom': self._val(item, 'UOM'),
                    'warehouse': self._val(item, 'Warehouse'),
                    'config_id': self.config_id.id,
                    'import_state': 'staged',
                    'import_message': 'Data API Imported',
                    'selected': True,
                    'sync_date': fields.Datetime.now(),
                }

                # === PRINT DATA HEADER ===
                # print("==========================================================================================")
                # print("HEADER DATA:")
                # for h_key, h_val in header.items():
                    # print(f"{h_key:<25} : {h_val}")

                reference_nbr = header.get('reference_nbr')
                assembly_key = reference_nbr or header.get('external_id') or f'row-{item_index}'
                cached_assembly = assemblies_by_reference.get(assembly_key)
                if cached_assembly:
                    assembly, unchanged_assembly = cached_assembly
                else:
                    existing_assembly = staging_header.search([
                        ('reference_nbr', '=', reference_nbr),
                    ], limit=1) if reference_nbr else staging_header.browse()
                    unchanged_assembly = bool(
                        existing_assembly
                        and (
                            not header.get('last_modified_datetime')
                            or existing_assembly.last_modified_datetime == header['last_modified_datetime']
                        )
                    )
                    if existing_assembly:
                        assembly = existing_assembly
                        if not unchanged_assembly:
                            existing_assembly.component_ids.unlink()
                            existing_assembly.write(header)
                    else:
                        # Protect the transaction if another fetch creates this
                        # globally unique reference after the search above.
                        try:
                            with self.env.cr.savepoint():
                                assembly = staging_header.with_context(
                                    mail_create_nosubscribe=True,
                                    mail_create_nolog=True,
                                ).create(header)
                        except IntegrityError:
                            if not reference_nbr:
                                raise
                            assembly = staging_header.search([
                                ('reference_nbr', '=', reference_nbr),
                            ], limit=1)
                            if not assembly:
                                raise
                            unchanged_assembly = bool(
                                not header.get('last_modified_datetime')
                                or assembly.last_modified_datetime == header['last_modified_datetime']
                            )
                            if not unchanged_assembly:
                                assembly.component_ids.unlink()
                                assembly.write(header)
                    assemblies_by_reference[assembly_key] = (assembly, unchanged_assembly)
                print(f"Created staging header record with ID {assembly.id} for ReferenceNbr {header['reference_nbr']}")

                stock_components = (item.get('KitAssemblyGIDetails'))
                if isinstance(stock_components, dict):
                    stock_components = stock_components.get('value', []) or []
                if not isinstance(stock_components, list):
                    stock_components = []
                stock_components = [
                    component for component in stock_components
                    if isinstance(component, dict)
                ]

                if not stock_components and self._val(item, 'LineStockInventoryID'):
                    stock_components = [item]

                if not stock_components:
                    if assembly_key not in empty_headers_seen:
                        result.append(dict(header, line_nbr='0'))
                        empty_headers_seen.add(assembly_key)
                    continue

                # === PRINT DATA COMPONENT ===
                # print("COMPONENTS:")
                for component in stock_components:
                    line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
                    component_external_id = component.get('id', '') or ''
                    component_key = component_external_id or (f'line-{line_nbr}' if line_nbr else False)
                    seen_component_keys = components_seen_by_reference.setdefault(assembly_key, set())
                    if component_key and component_key in seen_component_keys:
                        continue
                    if component_key:
                        seen_component_keys.add(component_key)

                    # Buat dictionary component data untuk mempermudah perulangan print
                    component_data = {
                        'line_external_id': component.get('id', '') or '',
                        'line_note': self._val(component, 'LineNote') or self._val(component, 'note'),
                        'line_note_id': self._val(component, 'LineNoteID'),
                        'line_inventory_id': self._val(component, 'LineInventoryID') or self._val(component, 'InventoryID'),
                        'line_component_qty': self._val(component, 'ComponentQty'),
                        'line_nbr': str(line_nbr),
                        'line_location_id': self._val(component, 'LineLocationID') or self._val(component, 'LocationID'),
                        'line_quantity': self._val(component, 'LineQty') or self._val(component, 'Qty'),
                        'line_reason_code': self._val(component, 'ReasonCode'),
                        'stock_inventory_id': self._val(component, 'LineStockInventoryID') or self._val(component, 'StockInventoryID'),
                        'line_uom': self._val(component, 'LineUOM') or self._val(component, 'UOM'),
                        'assembly_id': assembly.id,  # Simpan component dengan relasi ke header yang sudah dibuat, bisa dihapus jika tidak perlu
                    }
                    
                    # Print setiap field di dalam component ini dengan awalan '--'
                    # print("  ----------------------------------------")
                    # for c_key, c_val in component_data.items():
                        # print(f"  -- {c_key:<25} : {c_val}")

                    if not unchanged_assembly:
                        self.env['acumatica.kit.assembly.component'].create(component_data)
                    # print(f"  Created staging component record with ID {assembly_line.id} for LineNbr {component_data['line_nbr']} under ReferenceNbr {header['reference_nbr']}")
                    
                    # Keep flattening fetched rows even when the header is already current.
                    result.append({**header, **component_data})
                
                # print("==========================================================================================")


            # for item in raw_data:
            #     header = {
            #         'external_id': item.get('id', '') or '',
            #         'row_number': item.get('rowNumber', 0) or 0,
            #         'description': self._val(item, 'Description'),
            #         'inventory_id': self._val(item, 'InventoryID'),
            #         'last_modified_datetime': self._val(item, 'LastModifiedDateTime'),
            #         'location': self._val(item, 'Location'),
            #         'post_period': self._val(item, 'PostPeriod'),
            #         'quantity': self._val(item, 'Qty'),
            #         'reason_code': self._val(item, 'ReasonCode'),
            #         'reference_nbr': self._val(item, 'ReferenceNbr'),
            #         'requested_on': self._val(item, 'RequestedOn'),
            #         'revision': self._val(item, 'Revision'),
            #         'status': self._val(item, 'Status'),
            #         'type': self._val(item, 'Type'),
            #         'uom': self._val(item, 'UOM'),
            #         'warehouse': self._val(item, 'Warehouse'),


            #     }

            #     stock_components = item.get('StockComponents') or []
            #     if isinstance(stock_components, dict):
            #         stock_components = stock_components.get('value', []) or []
            #     if not isinstance(stock_components, list):
            #         stock_components = []

            #     if not stock_components:
            #         result.append(dict(header, line_nbr='0'))
            #         continue

            #     for component in stock_components:
            #         line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
            #         result.append({
            #             **header,
            #             'line_external_id': component.get('id', '') or '',
            #             'line_note': component.get('note', {}).get('value', '') or '',
            #             'line_inventory_id': self._val(component, 'InventoryID'),
            #             'line_component_qty': self._val(component, 'ComponentQty'),
            #             'line_nbr': str(line_nbr),
            #             'line_location_id': self._val(component, 'LocationID'),
            #             'line_quantity': self._val(component, 'Qty'),
            #             'line_reason_code': self._val(component, 'ReasonCode'),
            #             'stock_inventory_id': self._val(component, 'StockInventoryID'),
            #             'line_uom': self._val(component, 'UOM'),
            #         })

            
            _logger.info(
                'Berhasil ambil %s rows Kit Assembly dari Acumatica (skip=%s, top=%s)',
                len(result), limit,
            )
            return result
        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    @staticmethod
    def _val(item, key):
        if not isinstance(item, dict):
            return ''
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Data Kit Assembly dari Acumatica',
            'res_model': 'acumatica.kit.assembly.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
            'context':   {'default_config_id': self.config_id.id},
        }

    # =========================
    # IMPORT
    # =========================
    def action_import_all_pending(self):
        self.ensure_one()

        Line = self.env['acumatica.kit.assembly.line']

        domain = [
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ]

        total = Line.search_count(domain)

        if not total:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        _logger.info("IMPORT ALL START: total=%s", total)

        batch_size = 1000
        processed = 0

        while True:
            lines = Line.search(domain, limit=batch_size)

            if not lines:
                break

            _logger.info(
                "PROCESSING BATCH: %s records (processed=%s/%s)",
                len(lines), processed, total
            )

            # Import batch
            lines._do_import()

            # Commit biar tidak numpuk di memory & tidak freeze
            self.env.cr.commit()

            processed += len(lines)

            _logger.info(
                "BATCH DONE: processed=%s/%s",
                processed, total
            )

        _logger.info("IMPORT ALL DONE: total processed=%s", processed)

        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import Kit Assembly',
            'res_model': 'acumatica.kit.assembly.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
        
    def action_import_batch(self):
        self.ensure_one()
        Line = self.env['acumatica.kit.assembly.line']

        domain = [
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ]

        lines = Line.search(domain, limit=1000)
        if not lines:
            raise UserError('Tidak ada data pending untuk diimport.')

        lines._do_import()
        self.env.cr.commit()

        remaining = Line.search_count(domain)
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Batch Import Selesai',
        #         'message': f'{len(lines)} data diproses. Sisa pending: {remaining}',
        #         'type': 'success',
        #         'sticky': False,
        #     },
        # }
