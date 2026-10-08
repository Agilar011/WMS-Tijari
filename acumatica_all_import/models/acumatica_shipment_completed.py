import logging
import time
from dateutil import parser as dateutil_parser
import requests

from odoo import fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AcumaticaShipmentCompletedStaging(models.Model):
    _name = 'acumatica.shipment.completed.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
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

    issue_nbr = fields.Char(string='Issue Number')
    fob_point = fields.Char(string='FOB Point')
    fob_point_description = fields.Char(string='FOB Point Description')
    location_id = fields.Char(string='Location ID')
    note_header = fields.Text(string='Note Header')
    note_header_id = fields.Char(string='Note Header ID')
    phone = fields.Char(string='Phone')
    site_id_description = fields.Char(string='Site ID Description')

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

    last_modified_datetime = fields.Datetime(
        string='Last Modified Date',
        index=True,
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
        index=True,
    )

    import_message = fields.Text(
        string='Generation Message',
    )

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        ondelete='set null',
        index=True,
    )

    sync_date = fields.Datetime(
        string='Tanggal Sync',
    )

    is_used = fields.Boolean('is_used', default=False)

    _sql_constraints = [
        (
            'shipment_completed_unique',
            'unique(shipment_nbr, config_id)',
            'Data Shipment Completed dari Acumatica sudah ada!'
        ),
    ]

    def action_reset_pending(self):
        self.filtered(lambda record: record.import_state == 'error').write({
            'import_state': 'staged',
            'import_message': False,
        })
        return True

    def action_update_stock_picking(self):
        """
        Process all shipment completed staging records.
        Each record is handled independently.
        """
        for record in self:
            record._action_update_stock_picking()

        return True

    def _action_update_stock_picking(self):
        """
        Process a single shipment completed staging record.
        """
        self.ensure_one()

        Picking = self.env['stock.picking']
        shipment_nbr = self.shipment_nbr

        savepoint_name = "shipment_completed_update"

        self.env.cr.execute(
            f"SAVEPOINT {savepoint_name}"
        )

        try:
            # ---------------------------------------------------------
            # Find Stock Picking
            # ---------------------------------------------------------
            picking = Picking.search([
                ('origin', '=', shipment_nbr),
                ('wms_state', '=', 'waiting_response')
            ], limit=1)

            if not picking:
                error_message = f"Dokumen {shipment_nbr} tidak ada di WMS."
                _logger.warning(
                    "SHIPMENT COMPLETED | SKIP | Stock Picking tidak ditemukan | "
                    "shipment_nbr=%s | staging_id=%s",
                    shipment_nbr,
                    self.id,
                )

                self.env.cr.execute(
                    f"ROLLBACK TO SAVEPOINT {savepoint_name}"
                )
                self.import_message = error_message

                return False

            # ---------------------------------------------------------
            # Get staging lines
            # ---------------------------------------------------------
            staging_lines = self.line_ids

            all_match = True

            # ---------------------------------------------------------
            # Compare staging quantity with DO quantity
            # ---------------------------------------------------------
            for move in picking.move_ids:

                staging_lines_for_product = staging_lines.filtered(
                    lambda line:
                        line.line_inventory_id
                        == move.product_id.default_code
                )

                if not staging_lines_for_product:
                    staging_qty = 0.0
                    all_match = False

                else:
                    staging_qty = sum(
                        staging_lines_for_product.mapped(
                            'line_quantity'
                        )
                    )

                    if not staging_qty:
                        all_match = False

                # -----------------------------------------------------
                # Staging quantity less than DO quantity
                # -----------------------------------------------------
                if staging_qty < move.quantity:
                    all_match = False

                # -----------------------------------------------------
                # Staging quantity exceeds DO quantity
                # -----------------------------------------------------
                elif staging_qty > move.quantity:
                    raise ValidationError(
                        f"Quantity {move.product_id.display_name} "
                        f"melebihi quantity DO. "
                        f"DO={move.quantity}, staging={staging_qty}"
                    )

                # -----------------------------------------------------
                # Update shipped quantity
                # -----------------------------------------------------
                move.shipped_qty = staging_qty

            # ---------------------------------------------------------
            # Determine shipment type
            # ---------------------------------------------------------
            picking.shipment_information = (
                'full_shipment'
                if all_match
                else 'partial'
            )

            # ---------------------------------------------------------
            # Confirm shipment
            # ---------------------------------------------------------
            picking.action_confirm_shipment()

            # ---------------------------------------------------------
            # Mark staging as used
            # ---------------------------------------------------------
            self.is_used = True

            # ---------------------------------------------------------
            # Commit current savepoint
            # ---------------------------------------------------------
            self.env.cr.execute(
                f"RELEASE SAVEPOINT {savepoint_name}"
            )

            _logger.info(
                "SHIPMENT COMPLETED | SUCCESS | "
                "shipment_nbr=%s | picking=%s | type=%s",
                shipment_nbr,
                picking.name,
                picking.shipment_information,
            )

            return True

        except Exception as e:

            # ---------------------------------------------------------
            # Rollback only this staging record
            # ---------------------------------------------------------
            self.env.cr.execute(
                f"ROLLBACK TO SAVEPOINT {savepoint_name}"
            )

            self.import_message = str(e)

            _logger.exception(
                "SHIPMENT COMPLETED | SKIP | "
                "shipment_nbr=%s | staging_id=%s | error=%s",
                shipment_nbr,
                self.id,
                e,
            )

            return False


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
        index=True,
    )

    sync_date = fields.Datetime(
        related='staging_id.sync_date',
        store=True,
    )
