import logging
import time
from datetime import datetime

import requests

from odoo import fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class ImportShipmentCompletedWizard(models.TransientModel):
    _name = 'import.shipment.completed.wizard'
    _description = 'Wizard Fetch Shipment Completed dari Acumatica'

    # =========================================================
    # CONFIG
    # =========================================================

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )

    # =========================================================
    # FILTER
    # =========================================================

    warehouse_value = fields.Char(
        string='Warehouse Value',
        default='WH33-FG',
    )

    start_date = fields.Date(
        string='Start Date',
    )

    end_date = fields.Date(
        string='End Date',
    )

    wh33_filter = fields.Boolean(
        string='Filter WH33',
        default=True,
    )

    # Tetap disediakan supaya kompatibel dengan Unified Wizard
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=5000,
    )

    batch_size = fields.Integer(
        string='Batch Size',
        default=50,
    )

    fetch_skip = fields.Integer(
        string='Skip Data',
        default=0,
    )

    # =========================================================
    # STATUS
    # =========================================================

    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
    ], default='draft')

    total_fetched = fields.Integer(
        string='Total Data Ditarik',
        readonly=True,
    )

    total_new = fields.Integer(
        string='Data Baru',
        readonly=True,
    )

    total_existing = fields.Integer(
        string='Data Diupdate',
        readonly=True,
    )

    # =========================================================
    # MAIN ACTION
    # =========================================================

    def action_fetch_data(self):
        self.ensure_one()

        if self.fetch_limit <= 0:
            raise UserError(
                'Maks Data Ditarik harus lebih besar dari 0.'
            )

        _logger.info(
            'Fetching Shipment Completed | Config: %s',
            self.config_id.display_name,
        )

        raw_data = self.fetch_shipment_completed_data()

        if not raw_data:
            raise UserError(
                'Tidak ada data Shipment Completed yang diterima dari API.'
            )

        result = self.create_staging_data(raw_data)

        self.write({
            'state': 'fetched',
            'total_fetched': result['total'],
            'total_new': result['new'],
            'total_existing': result['existing'],
        })

        return self._reopen()

    # =========================================================
    # FETCH API
    # =========================================================

    def fetch_shipment_completed_data(self):
        """
        Fetch data Shipment Completed dari Acumatica.

        API Shipment Completed menggunakan custom API dengan
        HTTP PUT tetapi response berupa data.
        """

        self.ensure_one()

        session = self.config_id._do_login()

        try:
            endpoint = (
                f"{self.config_id.api_url}/"
                f"{self.config_id.endpoint_name}"
            )

            params = {}
            if self.config_id.odata_expand:
                params["$expand"] = self.config_id.odata_expand

            session.headers.update({
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            })

            payload = {}

            # =================================================
            # FILTER WAREHOUSE
            # =================================================

            # if self.warehouse_value:
            #     payload['Warehouse'] = {
            #         'value': self.warehouse_value,
            #     }

            # =================================================
            # FILTER DATE
            # =================================================

            # if self.start_date:
            #     payload['StartDate'] = {
            #         'value': self.start_date.strftime('%Y-%m-%d'),
            #     }

            # if self.end_date:
            #     payload['EndDate'] = {
            #         'value': self.end_date.strftime('%Y-%m-%d'),
            #     }

            _logger.info(
                'Shipment Completed Request | Endpoint: %s',
                endpoint,
            )

            _logger.info(
                'Shipment Completed Request Payload: %s',
                payload,
            )

            response = session.put(
                endpoint,
                params=params,
                json={},
                timeout=800,
            )

            if response.status_code != 200:
                raise UserError(
                    'Gagal mengambil Shipment Completed '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

            response_data = response.json()

            rows = self._normalize_rows(response_data)

            _logger.info(
                'Shipment Completed received %s rows',
                len(rows),
            )

            # fetch_limit
            # if self.fetch_skip:
            #     rows = rows[self.fetch_skip:]

            # if self.fetch_limit:
            #     rows = rows[:self.fetch_limit]

            return rows

        except requests.exceptions.RequestException as error:
            _logger.exception(
                'Shipment Completed API Request Error'
            )

            raise UserError(
                f'Gagal menghubungi API Shipment Completed: {error}'
            )

        except Exception as error:
            _logger.exception(
                'Shipment Completed Fetch Error'
            )

            raise UserError(str(error))

        finally:
            self.config_id._do_logout(session)

    # =========================================================
    # CREATE / UPDATE STAGING
    # =========================================================

    def create_staging_data(self, api_data):
        self.ensure_one()

        Staging = self.env[
            'acumatica.shipment.completed.staging'
        ]
        Line = self.env[
            'acumatica.shipment.completed.staging.line'
        ]

        total = 0
        total_new = 0
        total_existing = 0

        # =====================================================
        # GROUP BY SHIPMENT NBR
        # =====================================================

        shipments = {}

        for item in api_data:
            shipment_nbr = self._val(item, 'ShipmentNbr')

            if not shipment_nbr:
                _logger.warning(
                    'Shipment Completed dilewati karena '
                    'tidak memiliki ShipmentNbr.'
                )
                continue

            shipments.setdefault(shipment_nbr, []).append(item)

        # =====================================================
        # PROCESS EACH SHIPMENT
        # =====================================================

        for shipment_nbr, items in shipments.items():

            total += 1

            # Ambil row pertama sebagai sumber HEADER
            header_item = items[0]

            header_vals = self._prepare_header_vals(header_item)

            # Semua row menjadi LINE
            line_vals = [
                self._prepare_line_vals(item)
                for item in items
            ]

            try:
                with self.env.cr.savepoint():

                    existing = Staging.search([
                        ('config_id', '=', self.config_id.id),
                        ('shipment_nbr', '=', shipment_nbr),
                    ], limit=1)

                    if existing:

                        # UPDATE HEADER
                        existing.write(header_vals)

                        # REPLACE LINES
                        existing.line_ids.unlink()

                        for vals in line_vals:
                            vals['staging_id'] = existing.id
                            Line.create(vals)

                        total_existing += 1

                        _logger.info(
                            'Shipment Completed UPDATED: %s',
                            shipment_nbr,
                        )

                    else:

                        header_vals['line_ids'] = [
                            (0, 0, vals)
                            for vals in line_vals
                        ]

                        Staging.create(header_vals)

                        total_new += 1

                        _logger.info(
                            'Shipment Completed CREATED: %s',
                            shipment_nbr,
                        )

            except Exception as error:
                _logger.exception(
                    'Error saving Shipment Completed %s',
                    shipment_nbr,
                )
                continue

        return {
            'total': total,
            'new': total_new,
            'existing': total_existing,
        }
    # =========================================================
    # PREPARE HEADER
    # =========================================================

    def _prepare_header_vals(self, item):

        return {
            'config_id': self.config_id.id,

            # Acumatica Identifier
            'acumatica_id': item.get('id'),
            'row_number': item.get('rowNumber'),
            'note': self._val(item, 'note'),
            'issue_nbr': self._val(item, 'IssueNbr'),
            'fob_point': self._val(item, 'FOBPoint'),
            'fob_point_description': self._val(item, 'FOBPointDescription'),
            'location_id': self._val(item, 'LocationID'),
            'note_header': self._val(item, 'NoteHeader'),
            'note_header_id': self._val(item, 'NoteHeaderID'),
            'phone': self._val(item, 'Phone'),
            'site_id_description': self._val(item, 'SiteIDDescription'),

            # Shipment
            'order_type': self._val(item, 'OrderType'),
            'shipment_nbr': self._val(item, 'ShipmentNbr'),
            'inventory_nbr': self._val(item, 'InvtRefNbr'),
            'ship_date': self._parse_datetime(
                self._val(item, 'ShipDate')
            ),
            'shipment_qty': self._float_val(
                item,
                'ShipmentQty'
            ),
            'shipment_type': self._val(
                item,
                'ShipmentType'
            ),
            'shipment_volume': self._float_val(
                item,
                'ShipmentVolume'
            ),
            'shipment_weight': self._float_val(
                item,
                'ShipmentWeight'
            ),
            'shipment_via': self._val(
                item,
                'ShipVia'
            ),
            'last_modified_datetime': self._parse_datetime(
                self._val(item, 'LastModifiedDateTime')
            ),
            'status': self._val(
                item,
                'Status'
            ),

            # Customer
            'customer_id': self._val(
                item,
                'CustomerID'
            ),
            'customer_name': self._val(
                item,
                'CustomerName'
            ),

            # Warehouse
            'warehouse_id': self._val(
                item,
                'WarehouseID'
            ),
            'to_warehouse_id': self._val(
                item,
                'ToWarehouseID'
            ),

            # Address
            'address_id': self._val(
                item,
                'AddressID'
            ),
            'address_line': self._val(
                item,
                'AddressLine'
            ),
            'building_id': self._val(
                item,
                'BuildingID'
            ),
            'city': self._val(
                item,
                'City'
            ),
            'country': self._val(
                item,
                'Country'
            ),
            'country_name': self._val(
                item,
                'CountryName'
            ),
            'state': self._val(
                item,
                'State'
            ),
            'state_name': self._val(
                item,
                'StateName'
            ),
            'postal_code': self._val(
                item,
                'PostalCode'
            ),

            # Tracking
            'import_state': 'staged',
            'import_message': 'Data API Imported',
            'selected': True,
            'sync_date': fields.Datetime.now(),
        }

    # =========================================================
    # PREPARE DETAILS
    # =========================================================

    def _prepare_line_vals(self, item):

        return {
            'acumatica_id': item.get('id'),
            'row_number': item.get('rowNumber'),
            'note': self._val(item, 'note'),

            'line_nbr': self._int_val(
                item, 'LineNbr'
            ),
            'line_inventory_id': self._val(
                item, 'LineInventoryID'
            ),
            'line_description': self._val(
                item, 'LineDescription'
            ),
            'line_free_item': self._bool_val(
                item, 'LineFreeItem'
            ),
            'line_quantity': self._float_val(
                item, 'LineQuantity'
            ),
            'line_uom': self._val(
                item, 'LineUOM'
            ),
            'location_id': self._val(
                item, 'LineLocation'
            ),
            'location_name': self._val(
                item, 'LocationName'
            ),
            'line_note': self._val(
                item, 'LineNote'
            ),
            'line_note_id': self._val(
                item, 'LineNoteID'
            ),
        }
    
    # =========================================================
    # ACTION VIEW STAGING
    # =========================================================

    def action_view_staging(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Shipment Completed dari Acumatica',
            'res_model': 'acumatica.shipment.completed.staging',
            'view_mode': 'list,form',
            'domain': [
                ('config_id', '=', self.config_id.id),
            ],
            'context': {
                'default_config_id': self.config_id.id,
            },
        }

    # =========================================================
    # RESET
    # =========================================================

    def action_reset(self):
        self.ensure_one()

        self.write({
            'state': 'draft',
            'total_fetched': 0,
            'total_new': 0,
            'total_existing': 0,
        })

        return self._reopen()

    # =========================================================
    # REOPEN
    # =========================================================

    def _reopen(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # =========================================================
    # HELPER
    # =========================================================

    @staticmethod
    def _val(item, key):

        value = item.get(key, {})

        if isinstance(value, dict):
            return value.get('value', '') or ''

        return value or ''

    @classmethod
    def _float_val(cls, item, key):

        value = cls._val(item, key)

        if value in (None, ''):
            return 0.0

        try:
            return float(value)

        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _int_val(cls, item, key):

        value = cls._val(item, key)

        if value in (None, ''):
            return 0

        try:
            return int(float(value))

        except (TypeError, ValueError):
            return 0

    @classmethod
    def _bool_val(cls, item, key):

        value = cls._val(item, key)

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() in (
            'true',
            '1',
            'yes',
            'y',
        )

    @staticmethod
    def _parse_datetime(value):

        if not value:
            return False

        try:
            value = value.replace('Z', '+00:00')

            return datetime.fromisoformat(value).replace(
                tzinfo=None
            )

        except Exception:

            return False

    @staticmethod
    def _normalize_rows(payload):

        if isinstance(payload, list):
            return payload

        if isinstance(payload, dict):

            if isinstance(payload.get('value'), list):
                return payload.get('value')

            if isinstance(payload.get('rows'), list):
                return payload.get('rows')

            if isinstance(payload.get('ShipmentCompletedGIDetails'), list):
                return payload.get(
                    'ShipmentCompletedGIDetails'
                )

        return []
