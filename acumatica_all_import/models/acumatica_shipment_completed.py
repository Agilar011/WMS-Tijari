import logging
import time
from dateutil import parser as dateutil_parser
import requests

from odoo import fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AcumaticaShipmentCompletedStaging(models.Model):
    _name = 'acumatica.shipment.completed.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Staging Shipment Completed dari Acumatica'
    _rec_name = 'shipment_nbr'
    _order = 'id desc'

    # =========================================================
    # ACUMATICA IDENTIFIER
    # =========================================================

    acumatica_id = fields.Char(
        string='Acumatica ID',
        required=True,
        index=True,
    )

    row_number = fields.Integer(
        string='Row Number',
    )

    note = fields.Text(
        string='Note',
    )

    # =========================================================
    # SHIPMENT
    # =========================================================

    order_type = fields.Char(
        string='Order Type',
        index=True,
    )

    shipment_nbr = fields.Char(
        string='Shipment Number',
        index=True,
    )

    inventory_nbr = fields.Char('Inventory Number')

    ship_date = fields.Datetime(
        string='Shipment Date',
    )

    shipment_qty = fields.Float(
        string='Shipment Quantity',
    )

    shipment_type = fields.Char(
        string='Shipment Type',
    )

    shipment_volume = fields.Float(
        string='Shipment Volume',
    )

    shipment_weight = fields.Float(
        string='Shipment Weight',
    )

    shipment_via = fields.Char(
        string='Shipment Via',
    )

    status = fields.Char(
        string='Status',
        index=True,
    )

    # =========================================================
    # CUSTOMER
    # =========================================================

    customer_id = fields.Char(
        string='Customer ID',
        index=True,
    )

    customer_name = fields.Char(
        string='Customer Name',
    )

    # =========================================================
    # WAREHOUSE
    # =========================================================

    warehouse_id = fields.Char(
        string='Warehouse ID',
        index=True,
    )

    to_warehouse_id = fields.Char(
        string='To Warehouse ID',
    )

    # =========================================================
    # ADDRESS
    # =========================================================

    address_id = fields.Char(
        string='Address ID',
    )

    address_line = fields.Char(
        string='Address',
    )

    building_id = fields.Char(
        string='Building ID',
    )

    city = fields.Char(
        string='City',
    )

    country = fields.Char(
        string='Country',
    )

    country_name = fields.Char(
        string='Country Name',
    )

    state = fields.Char(
        string='State',
    )

    state_name = fields.Char(
        string='State Name',
    )

    postal_code = fields.Char(
        string='Postal Code',
    )

    # =========================================================
    # STAGING DETAILS
    # =========================================================

    line_ids = fields.One2many(
        'acumatica.shipment.completed.staging.line',
        'staging_id',
        string='Details',
    )

    # =========================================================
    # IMPORT STATUS
    # =========================================================

    selected = fields.Boolean(
        string='Pilih',
        default=True,
    )

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ],
        string='Status',
        default='staged',
        readonly=True,
        index=True,
    )

    import_message = fields.Text(
        string='Generation Message',
        readonly=True,
    )

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        required=True,
        readonly=True,
        ondelete='cascade',
        index=True,
    )

    sync_date = fields.Datetime(
        string='Tanggal Sync',
        readonly=True,
    )

    _sql_constraints = [
        (
            'shipment_completed_unique',
            'unique(shipment_nbr, config_id)',
            'Data Shipment Completed dari Acumatica sudah ada!'
        ),
    ]

class AcumaticaShipmentCompletedStagingLine(models.Model):
    _name = 'acumatica.shipment.completed.staging.line'
    _description = 'Detail Staging Shipment Completed dari Acumatica'
    _order = 'staging_id, line_nbr'

    staging_id = fields.Many2one(
        'acumatica.shipment.completed.staging',
        string='Shipment Completed',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # =========================================================
    # ACUMATICA IDENTIFIER
    # =========================================================

    acumatica_id = fields.Char(
        string='Acumatica ID',
        index=True,
    )

    row_number = fields.Integer(
        string='Row Number',
    )

    note = fields.Text(
        string='Note',
    )

    # =========================================================
    # LINE DATA
    # =========================================================

    line_nbr = fields.Integer(
        string='Line Number',
    )

    line_inventory_id = fields.Char(
        string='Inventory ID',
        index=True,
    )

    line_description = fields.Text(
        string='Description',
    )

    line_free_item = fields.Boolean(
        string='Free Item',
    )

    line_quantity = fields.Float(
        string='Quantity',
    )

    line_uom = fields.Char(
        string='UOM',
    )

    location_id = fields.Char(
        string='Location ID',
    )

    location_name = fields.Char(
        string='Location Name',
    )

    line_note = fields.Text(
        string='Line Note',
    )

    line_note_id = fields.Char(
        string='Line Note ID',
    )

    # =========================================================
    # TRACKING
    # =========================================================

    config_id = fields.Many2one(
        related='staging_id.config_id',
        store=True,
        readonly=True,
        index=True,
    )

    sync_date = fields.Datetime(
        related='staging_id.sync_date',
        store=True,
        readonly=True,
    )

