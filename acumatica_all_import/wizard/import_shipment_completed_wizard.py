import logging
import time
from datetime import datetime

import requests

from odoo import fields, models
from odoo.exceptions import UserError
from ..utils import acumatica_data as _data



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
                self.env["acumatica.webhook.error.service"].send_error(
                    webhook_type="fetch",
                    webhook_name="Shipment Completed",
                    error=f"Gagal fetch Shipment Completed dari Acumatica (HTTP {response.status_code}).",
                    error_type="http",
                )
                raise UserError(
                    'Gagal mengambil Shipment Completed '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

            response_data = response.json()

            rows = _data.acumatica_rows(response_data, extra_keys=("ShipmentCompletedGIDetails",))

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
            shipment_nbr = _data.acumatica_value(item, 'ShipmentNbr')

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

                        if (
                            not header_vals.get('last_modified_datetime')
                            or existing.last_modified_datetime == header_vals['last_modified_datetime']
                        ):
                            continue

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
            'note': _data.acumatica_value(item, 'note'),
            'issue_nbr': _data.acumatica_value(item, 'IssueNbr'),
            'fob_point': _data.acumatica_value(item, 'FOBPoint'),
            'fob_point_description': _data.acumatica_value(item, 'FOBPointDescription'),
            'location_id': _data.acumatica_value(item, 'LocationID'),
            'note_header': _data.acumatica_value(item, 'NoteHeader'),
            'note_header_id': _data.acumatica_value(item, 'NoteHeaderID'),
            'phone': _data.acumatica_value(item, 'Phone'),
            'site_id_description': _data.acumatica_value(item, 'SiteIDDescription'),

            # Shipment
            'order_type': _data.acumatica_value(item, 'OrderType'),
            'shipment_nbr': _data.acumatica_value(item, 'ShipmentNbr'),
            'inventory_nbr': _data.acumatica_value(item, 'InvtRefNbr'),
            'ship_date': self._parse_datetime(
                _data.acumatica_value(item, 'ShipDate')
            ),
            'shipment_qty': self._float_val(
                item,
                'ShipmentQty'
            ),
            'shipment_type': _data.acumatica_value(
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
            'shipment_via': _data.acumatica_value(
                item,
                'ShipVia'
            ),
            'last_modified_datetime': self._parse_datetime(
                _data.acumatica_value(item, 'LastModifiedDateTime')
            ),
            'status': _data.acumatica_value(
                item,
                'Status'
            ),

            # Customer
            'customer_id': _data.acumatica_value(
                item,
                'CustomerID'
            ),
            'customer_name': _data.acumatica_value(
                item,
                'CustomerName'
            ),

            # Warehouse
            'warehouse_id': _data.acumatica_value(
                item,
                'WarehouseID'
            ),
            'to_warehouse_id': _data.acumatica_value(
                item,
                'ToWarehouseID'
            ),

            # Address
            'address_id': _data.acumatica_value(
                item,
                'AddressID'
            ),
            'address_line': _data.acumatica_value(
                item,
                'AddressLine'
            ),
            'building_id': _data.acumatica_value(
                item,
                'BuildingID'
            ),
            'city': _data.acumatica_value(
                item,
                'City'
            ),
            'country': _data.acumatica_value(
                item,
                'Country'
            ),
            'country_name': _data.acumatica_value(
                item,
                'CountryName'
            ),
            'state': _data.acumatica_value(
                item,
                'State'
            ),
            'state_name': _data.acumatica_value(
                item,
                'StateName'
            ),
            'postal_code': _data.acumatica_value(
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
            'note': _data.acumatica_value(item, 'note'),

            'line_nbr': self._int_val(
                item, 'LineNbr'
            ),
            'line_inventory_id': _data.acumatica_value(
                item, 'LineInventoryID'
            ),
            'line_description': _data.acumatica_value(
                item, 'LineDescription'
            ),
            'line_free_item': _data.acumatica_bool(
                item, 'LineFreeItem'
            , true_values=_data.DEFAULT_TRUE_VALUES),
            'line_quantity': self._float_val(
                item, 'LineQuantity'
            ),
            'line_uom': _data.acumatica_value(
                item, 'LineUOM'
            ),
            'location_id': _data.acumatica_value(
                item, 'LineLocation'
            ),
            'location_name': _data.acumatica_value(
                item, 'LocationName'
            ),
            'line_note': _data.acumatica_value(
                item, 'LineNote'
            ),
            'line_note_id': _data.acumatica_value(
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


    @classmethod
    def _float_val(cls, item, key):

        value = _data.acumatica_value(item, key)

        if value in (None, ''):
            return 0.0

        try:
            return float(value)

        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _int_val(cls, item, key):

        value = _data.acumatica_value(item, key)

        if value in (None, ''):
            return 0

        try:
            return int(float(value))

        except (TypeError, ValueError):
            return 0


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
