from datetime import datetime
from odoo import models, fields, api
from odoo.fields import Datetime
from odoo.exceptions import UserError

from dateutil import parser as dateutil_parser
import logging

_logger = logging.getLogger(__name__)


class AcumaticaKitAssembly(models.Model):
    _name = 'acumatica.kit.assembly'
    _description = 'Acumatica Kit Assembly'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']

    name = fields.Char(
        string='Reference Number',
        required=True,
        index=True,
        tracking=True,
    )

    external_id = fields.Char(
        string='External ID',
        index=True,
    )

    row_number = fields.Integer()

    description = fields.Char()

    inventory_id = fields.Char(
        string='Finished Good Inventory ID',
        index=True,
    )

    last_modified_datetime = fields.Char(string='LastModifiedDateTime')

    location = fields.Char()
    building_id = fields.Char(string='Building ID')
    note_header = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')

    post_period = fields.Char()
    date = fields.Date(string='Date')

    quantity = fields.Float()

    reason_code = fields.Char()

    reference_nbr = fields.Char(
        required=True,
        index=True,
    )

    requested_on = fields.Date()

    revision = fields.Char()

    status = fields.Char()

    document_only = fields.Boolean(string='Document Only')

    type = fields.Char()

    uom = fields.Char()

    warehouse = fields.Char()

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged', tracking=True)

    import_message = fields.Text(string='Generation Message', tracking=True)
    selected = fields.Boolean(string='Pilih', default=True)
    sync_date = fields.Datetime(string='Tanggal Sync')

    mrp_production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
    )

    component_ids = fields.One2many(
        'acumatica.kit.assembly.component',
        'assembly_id',
        string='Components',
    )

    config_id = fields.Many2one(
            'acumatica.config',
            string='Konfigurasi',
            ondelete='cascade',
        )
    _sql_constraints = [
        (
            'reference_nbr_unique',
            'unique(reference_nbr)',
            'Reference Number must be unique.'
        )
    ]

    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def _do_import(self):
        print("Starting import process...")

        Manufacturing = self.env["mrp.production"]
        PickingType = self.env["stock.picking.type"]
        Warehouse = self.env["stock.location.acumatica"]
        HeaderReference = self.env["acumatica.kit.assembly"]
        ComponentReference = self.env["acumatica.kit.assembly.component"]
        Product = self.env["product.product"]

        created = 0
        updated = 0
        error = 0

        # MO terakhir yang berhasil diproses
        last_manufacturing = Manufacturing

        for reference_nbr in self.mapped("reference_nbr"):
            records = self.filtered(lambda line: line.reference_nbr == reference_nbr)
            try:
                # ---------------------------------------------------------
                # Setiap reference punya savepoint sendiri.
                # Kalau gagal, hanya reference ini yang di-rollback.
                # ---------------------------------------------------------
                with self.env.cr.savepoint():

                    # -----------------------------------------------------
                    # HEADER
                    # -----------------------------------------------------
                    header = HeaderReference.search(
                        [("name", "=", reference_nbr)],
                        limit=1,
                    )

                    if not header:
                        raise ValueError(
                            f"Header tidak ditemukan: {reference_nbr}"
                        )

                    print(f"Header Value: {header.name}")

                    # -----------------------------------------------------
                    # WAREHOUSE
                    # -----------------------------------------------------
                    warehouse = Warehouse.search(
                        [("code", "=", header.warehouse)],
                        limit=1,
                    )

                    if not warehouse:
                        raise ValueError(
                            f"Warehouse tidak ditemukan: {header.warehouse}"
                        )

                    warehouse_record = warehouse.odoo_location_id.warehouse_id

                    if not warehouse_record:
                        raise ValueError(
                            f"Warehouse Odoo tidak ditemukan untuk: "
                            f"{header.warehouse}"
                        )

                    # -----------------------------------------------------
                    # FINISHED PRODUCT
                    # -----------------------------------------------------
                    finished_product = Product.search(
                        [("default_code", "=", header.inventory_id)],
                        limit=1,
                    )

                    if not finished_product:
                        raise ValueError(
                            f"Finished product tidak ditemukan: "
                            f"{header.inventory_id}"
                        )

                    # -----------------------------------------------------
                    # FIND EXISTING MO
                    # -----------------------------------------------------
                    manufacturing = Manufacturing.search(
                        [("origin", "=", header.name)],
                        limit=1,
                    )
                    picking_type = manufacturing.picking_type_id if manufacturing else PickingType.search(
                        [
                            ("name", "=", "Manufacturing"),
                            ("warehouse_id", "=", warehouse_record.id),
                        ],
                        limit=1,
                    )

                    if not picking_type:
                        raise ValueError(
                            "Manufacturing Picking Type tidak ditemukan "
                            f"untuk warehouse: {warehouse_record.display_name}"
                        )
                    # -----------------------------------------------------
                    # CREATE / UPDATE MO
                    # -----------------------------------------------------
                    if manufacturing:
                        if manufacturing.state not in ('draft', 'cancel'):
                            raise UserError(
                                f'Manufacturing Order {reference_nbr} sudah berada pada state '
                                f'{manufacturing.state}, tidak bisa diupdate.'
                            )
                        manufacturing.write({
                            'product_id': finished_product.id,
                            'product_qty': header.quantity,
                            'product_uom_id': finished_product.uom_id.id,
                            'date_start': header.requested_on,
                            'picking_type_id': picking_type.id,
                            'warehouse_id': warehouse_record.id,
                            'location_src_id': picking_type.default_location_src_id.id,
                            'location_dest_id': picking_type.default_location_dest_id.id,
                            'company_id': warehouse_record.company_id.id,
                        })
                        manufacturing.move_raw_ids.unlink()
                        action_state = 'updated'
                        updated += 1
                        print(
                            f"MO sudah ada: "
                            f"{manufacturing.display_name}"
                        )

                    else:
                        manufacturing = Manufacturing.create({
                            "origin": reference_nbr,
                            "product_id": finished_product.id,
                            "product_qty": header.quantity,
                            "product_uom_id": finished_product.uom_id.id,
                            "date_start": header.requested_on,
                            "user_id": self.env.uid,
                            "picking_type_id": picking_type.id,
                            "warehouse_id": warehouse_record.id,
                            "location_src_id": (
                                picking_type.default_location_src_id.id
                            ),
                            "location_dest_id": (
                                picking_type.default_location_dest_id.id
                            ),
                            "company_id": warehouse_record.company_id.id,
                        })
                        action_state = 'created'

                        created += 1

                        print(
                            f"MO berhasil dibuat: "
                            f"{manufacturing.display_name}"
                        )

                    last_manufacturing = manufacturing

                    # -----------------------------------------------------
                    # COMPONENTS
                    # -----------------------------------------------------
                    components = ComponentReference.search([
                        ("assembly_id", "=", header.id),
                    ])

                    raw_moves = []

                    for component in components:

                        component_product = Product.search(
                            [
                                (
                                    "default_code",
                                    "=",
                                    component.stock_inventory_id,
                                )
                            ],
                            limit=1,
                        )

                        if not component_product:
                            raise ValueError(
                                "Component product tidak ditemukan: "
                                f"{component.stock_inventory_id}"
                            )

                        raw_moves.append(
                            (
                                0,
                                0,
                                {
                                    "product_id": component_product.id,
                                    'product_uom_qty': component.line_quantity,
                                    'product_uom': component_product.product_tmpl_id.uom_id.id,

                                    "location_id": picking_type.default_location_src_id.id,
                                    "location_dest_id": picking_type.default_location_dest_id.id,

                                    "picking_type_id": picking_type.id,
                                    "warehouse_id": manufacturing.warehouse_id.id,

                                    "raw_material_production_id": manufacturing.id,
                                },
                            )
                        )

                    # -----------------------------------------------------
                    # RAW MATERIAL MOVES
                    # -----------------------------------------------------
                    if raw_moves and not manufacturing.exists():
                        raise ValueError(
                            "Manufacturing Order sudah tidak tersedia."
                        )

                    if raw_moves:
                        manufacturing.write({
                            "move_raw_ids": raw_moves,
                        })

                        print(
                            f"Raw moves berhasil dibuat: "
                            f"{len(raw_moves)}"
                        )

                    records.write({
                        "import_message": (
                            f"Created: {manufacturing.display_name}"
                            if manufacturing
                            else "Created"
                        ),
                        "mrp_production_id": manufacturing.id if manufacturing else False,
                        "import_state": action_state,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(reference_nbr, 'kit_assembly')

                    # _logger.warning("""
                    #     ========== RAW MOVE AFTER CREATE ==========
                    #     MO              : %s (%s)
                    #     MO WAREHOUSE    : %s (%s)
                    #     """,
                    #         manufacturing.name,
                    #         manufacturing.id,
                    #         manufacturing.warehouse_id.display_name,
                    #         manufacturing.warehouse_id.id,
                    # )

                    # for move in manufacturing.move_raw_ids:
                    #     _logger.warning("""
                    # RAW MOVE
                    #     ID              : %s
                    #     PRODUCT         : %s
                    #     WAREHOUSE       : %s (%s)
                    #     PICKING TYPE    : %s (%s)
                    #     SOURCE          : %s (%s)
                    #     DESTINATION     : %s (%s)
                    #     RAW MO          : %s
                    # """,
                    #         move.id,
                    #         move.product_id.display_name,
                    #         move.warehouse_id.display_name,
                    #         move.warehouse_id.id,
                    #         move.picking_type_id.display_name,
                    #         move.picking_type_id.id,
                    #         move.location_id.display_name,
                    #         move.location_id.id,
                    #         move.location_dest_id.display_name,
                    #         move.location_dest_id.id,
                    #         move.raw_material_production_id.id,
                    #     )

            except Exception as e:
                error += 1

                print(
                    f"ERROR processing {reference_nbr}: "
                    f"{type(e).__name__}: {e}"
                )
                records.write({
                    "import_message": f"{type(e).__name__}: {e}",
                    "mrp_production_id": False,
                    "import_state": "error",
                })
                header_payload = header.read()[0] if 'header' in locals() and header and header.exists() else {}
                component_records = components if 'components' in locals() else self.env['acumatica.kit.assembly.component']
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    records[:1] or self,
                    [f"{type(e).__name__}: {e}"],
                    api_acumatica='kit_assembly',
                    operation_type='manufacturing',
                    origin=reference_nbr,
                    location=header.warehouse if 'header' in locals() and header else False,
                    location_dest=header.location if 'header' in locals() and header else False,
                    scheduled_date=header.requested_on if 'header' in locals() and header else False,
                    total_qty=header.quantity if 'header' in locals() and header else 0.0,
                    payload={'header': header_payload},
                    line_payloads=[{
                        'inventory_id': component.stock_inventory_id or False,
                        'product_name': component.line_inventory_id or False,
                        'qty': component.line_quantity,
                        'uom': component.line_uom or False,
                        'payload': component.read()[0] if component.exists() else {},
                    } for component in component_records],
                )

        # -------------------------------------------------------------
        # RESULT
        # -------------------------------------------------------------
        total = len(self.mapped("reference_nbr"))

        msg = (
            "Import Kit Assembly selesai.\n\n"
            f"Total Reference Number : {total}\n"
            f"Manufacturing Order dibuat : {created}\n"
            f"Manufacturing Order sudah ada : {updated}\n"
            f"Error : {error}"
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Import Kit Assembly",
                "message": msg,
                "type": "success" if error == 0 else "danger",
                "sticky": True,
            },
        }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'staged',
            'import_message': False,
        })

    def action_open_product(self):
        self.ensure_one()
        if not self.odoo_product_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id':    self.odoo_product_id.id,
            'view_mode': 'form',
        }

    def action_open_manufacturing(self):
        self.ensure_one()
        if not self.mrp_production_id:
            raise UserError('Manufacturing Order belum dibuat.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.mrp_production_id.id,
            'view_mode': 'form',
        }


class AcumaticaKitAssemblyComponent(models.Model):
    _name = 'acumatica.kit.assembly.component'
    _description = 'Acumatica Kit Assembly Component'

    assembly_id = fields.Many2one(
        'acumatica.kit.assembly',
        required=True,
        ondelete='cascade',
    )

    line_external_id = fields.Char(
        required=True,
        index=True,
    )

    line_nbr = fields.Integer()

    line_note = fields.Text()
    line_note_id = fields.Char(string='Line Note ID')

    line_inventory_id = fields.Char()

    line_component_qty = fields.Float()

    line_location_id = fields.Char()

    line_quantity = fields.Float()

    line_reason_code = fields.Char()

    stock_inventory_id = fields.Char(
        string='Component Inventory ID',
        index=True,
    )

    line_uom = fields.Char()

    product_id = fields.Many2one(
        'product.product',
        string='Matched Product',
    )

    import_message = fields.Text(string='Generation Message', tracking=True)



class AcumaticaKitAssemblyLine(models.Model):
    """
    Tabel staging: hasil tarikan data Kit Assembly dari Acumatica.
    Target model Odoo: product.template

    Mapping:
      InventoryID          → default_code              (Mandatory)
      Description          → name                      (Mandatory)
      ItemType             → type                      (Mandatory)
      ItemClass            → adt_item_class             (Mandatory, to be)
      ItemStatus           → adt_item_status            (Mandatory, to be)
      BaseUOM              → uom_id / uom_po_id         (Mandatory, lookup by name)
      ValuationMethod      → adt_valuation_method       (Mandatory, to be)
      LastModifiedDateTime → adt_acumatica_write_date (Mandatory, to be)
    """
    _name        = 'acumatica.kit.assembly.line'
    _description = 'Data Kit Assembly dari Acumatica (Staging)'
    _order       = 'row_number asc'


    # 'external_id':item.get("id", "") or "",
    # 'row_number': item.get("rowNumber", 0),
    # 'description': val(item, "Description"),
    # 'inventory_id': val(item, "InventoryID"),
    # 'last_modified_datetime': val(item, "LastModifiedDateTime"),
    # 'location': val(item, "Location"),
    # 'post_period': val(item, "PostPeriod"),
    # 'quantity': val(item, "Qty"),
    # 'reason_code':val(item, "ReasonCode"),
    # 'reference_nbr':val(item, "ReferenceNbr"),
    # 'requested_on':val(item, "RequestedOn"),
    # 'revision':val(item, "Revision"),
    # 'status':val(item, "Status"),
    # 'type':val(item, "Type"),
    # 'uom': val(item, "UOM"),
    # 'warehouse': val(item, "Warehouse"),


    # 'line_external_id': component.get('id', '') or '',
    # 'line_note': component.get('note', {}).get('value', '') or '',
    # 'inventory_id': self._val(component, 'InventoryID'),
    # 'line_nbr': str(line_nbr),
    # 'line_location_id': self._val(component, 'LocationID'),
    # 'line_reason_code': self._val(component, 'ReasonCode'),
    # 'stock_inventory_id': self._val(component, 'StockInventoryID'),
    # 'uom_code': self._val(component, 'UOM'),

    # ─── Data mentah dari Acumatica ──────────────────
    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Acumatica')
    inventory_id = fields.Char(string='InventoryID')
    description = fields.Char(string='Description')
    last_modified_datetime = fields.Char(string='LastModifiedDateTime')
    location = fields.Char(string='Location')
    note_header = fields.Char(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')
    post_period = fields.Char(string='PostPeriod')
    date = fields.Char(string='Date')
    quantity = fields.Char(string='Qty')
    reason_code = fields.Char(string='ReasonCode')
    reference_nbr = fields.Char(string='ReferenceNbr')
    requested_on = fields.Char(string='RequestedOn')
    revision = fields.Char(string='Revision')
    status = fields.Char(string='Status')
    type = fields.Char(string='Type')
    uom = fields.Char(string='uom')
    warehouse = fields.Char(string='Warehouse')

    line_external_id = fields.Char(string='Line UUID')
    line_note = fields.Char(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')
    line_inventory_id = fields.Char(string='Line InventoryID')
    line_component_qty = fields.Char(string='Line Component Qty')
    line_nbr = fields.Char(string='Line Nbr')
    line_location_id = fields.Char(string='Line LocationID')
    line_quantity = fields.Char(string='Line Quantity')
    line_reason_code = fields.Char(string='Line ReasonCode')
    stock_inventory_id = fields.Char(string='Stock InventoryID')
    line_uom = fields.Char(string='Line UOM')

    RMALocationID = fields.Char(string='RMA Location ID')
    WarehouseID = fields.Char(string='Warehouse ID')
    BuildingID = fields.Char(string='Building ID')

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', tracking=True)

    import_message   = fields.Char(string='Generation Message',         )
    odoo_product_id  = fields.Many2one('product.template', string='Document Reference')
    odoo_bom_id = fields.Many2one('mrp.bom', string='BOM di Odoo')
    selected         = fields.Boolean(string='Pilih',           default=True)

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync')
    warehouse_code = fields.Char(string='Warehouse Code')
    location_dest_code = fields.Char(string='Location Dest Code')
    header_location_code = fields.Char(string='Header Location Code')
    uom_code = fields.Char(string='UOM Code')
    receipt_nbr = fields.Char(string='Receipt Nbr')
    po_number = fields.Char(string='PO Number')


    # ─── Helpers ─────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    # ItemType Acumatica → type Odoo
    # 'consu' = storable/consumable (Odoo 17/18 pakai 'consu' untuk goods)
    ITEM_TYPE_MAP = {
        'finished good': 'consu',
        'component':     'consu',
        'non-stock':     'consu',
        'service':       'service',
        'labor':         'service',
        'charge':        'service',
    }

    # ValuationMethod Acumatica → adt_valuation_method selection
    VALUATION_MAP = {
        'FIFO':     'FIFO',
        'Average':  'Average',
        'Standard': 'Standard',
        'Specific': 'Specific',
    }

    # ItemStatus Acumatica → adt_item_status selection
    STATUS_MAP = {
        'Active':       'Active',
        'Inactive':     'Inactive',
        'ToDelete':     'ToDelete',
        'NoSales':      'NoSales',
        'NoPurchases':  'NoPurchases',
        'NoRequest':    'NoRequest',
    }

    def _resolve_uom(self, uom_name):
        """
        Lookup uom.uom by name (case-insensitive).
        UOM sudah diimport sebelumnya ke uom.uom.
        Return: uom.uom record atau browse() jika tidak ditemukan.
        """
        if not uom_name:
            return self.env['uom.uom'].browse()
        uom = self.env['uom.uom'].search([('name', '=ilike', uom_name)], limit=1)
        return uom

    def _find_existing_product(self, rec):
        """Cari product.template by default_code (InventoryID)."""
        Product = self.env['product.template']
        if rec.inventory_id:
            found = Product.search([('default_code', '=', rec.inventory_id)], limit=1)
            if found:
                return found
        return Product.browse()

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        code = line.warehouse_code
        warehouse = False
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', code)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_destination_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.location_dest_code or line.header_location_code
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom




    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def _do_import(self):
        print("Starting import process...")
        Manufacturing = self.env['mrp.production']
        PickingType = self.env['stock.picking.type']
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        Warehouse = self.env['stock.warehouse']
        mapping_location = self.env['stock.location.acumatica']
        header_reference = self.env['acumatica.kit.assembly']
        component_reference = self.env['acumatica.kit.assembly.component']
        stock_picking = self.env['stock.picking']
        Move = self.env['stock.move']
        looping_count = 0



        created = 0
        updated = 0
        error = 0

        # proses per reference number
        for reference_nbr in self.mapped('reference_nbr'):
            records = self.filtered(lambda line: line.reference_nbr == reference_nbr)
            header = header_reference.search([('name', '=', reference_nbr)], limit=1)
            component_lines = component_reference
            try:
                with self.env.cr.savepoint():
                    if not header:
                        raise UserError(f"Header tidak ditemukan: {reference_nbr}")

                    warehouse = Warehouse.search([('code', '=', header.warehouse)], limit=1)
                    if not warehouse:
                        raise UserError(f"Warehouse tidak ditemukan untuk: {header.warehouse or '-'}")

                    processed_product = self.env['product.product'].search([
                        ('default_code', '=', header.inventory_id),
                    ], limit=1)
                    if not processed_product:
                        raise UserError(
                            f"Finished product tidak ditemukan untuk InventoryID: "
                            f"{header.inventory_id or '-'}"
                        )

                    existing_manufacturing = header.mrp_production_id or self.env['mrp.production'].search(
                        [('origin', '=', header.name)], limit=1,
                    )
                    picking_type = existing_manufacturing.picking_type_id if existing_manufacturing else PickingType.search([
                        ('name', '=', 'Manufacturing'),
                        ('warehouse_id', '=', warehouse.id),
                    ], limit=1)
                    if not picking_type:
                        raise UserError(
                            f"Manufacturing Picking Type tidak ditemukan untuk warehouse: "
                            f"{warehouse.display_name}"
                        )

                    component_lines = component_reference.search([('assembly_id', '=', header.id)])
                    for item in component_lines:
                        component_product = self.env['product.product'].search([
                            ('default_code', '=', item.stock_inventory_id),
                        ], limit=1)
                        if not component_product:
                            raise UserError(
                                f"Component product tidak ditemukan untuk InventoryID: "
                                f"{item.stock_inventory_id or '-'}"
                            )

                    vals = {
                        'origin': reference_nbr,
                        'product_id': processed_product.id,
                        'product_qty': header.quantity,
                        'product_uom_id': processed_product.uom_id.id,
                        'user_id': self.env.uid,
                        'picking_type_id': picking_type.id,
                        'location_src_id': picking_type.default_location_src_id.id,
                        'location_dest_id': picking_type.default_location_dest_id.id,
                        'company_id': warehouse.company_id.id,
                    }
                    manufacturing_check = self.env['mrp.production'].search([('origin', '=', header.name)], limit=1)
                    if manufacturing_check:
                        if manufacturing_check.state not in ('draft', 'cancel'):
                            raise UserError(
                                f'Manufacturing Order {reference_nbr} sudah berada pada state '
                                f'{manufacturing_check.state}, tidak bisa diupdate.'
                            )
                        manufacturing = manufacturing_check
                        manufacturing.write(vals)
                        manufacturing.move_raw_ids.unlink()
                        updated += 1
                    else:
                        manufacturing = Manufacturing.create(vals)
                        created += 1

                    raw_move_vals = []
                    for item in component_lines:
                        component_product = self.env['product.product'].search([
                            ('default_code', '=', item.stock_inventory_id),
                        ], limit=1)
                        raw_move_vals.append({
                            'name': component_product.display_name,
                            'product_id': component_product.id,
                            'product_uom_qty': item.line_quantity,
                            'product_uom': component_product.uom_id.id,
                            'location_id': picking_type.default_location_src_id.id,
                            'location_dest_id': picking_type.default_location_dest_id.id,
                            'picking_type_id': picking_type.id,
                            'warehouse_id': manufacturing.warehouse_id.id,
                            'raw_material_production_id': manufacturing.id,
                        })
                    if raw_move_vals:
                        Move.create(raw_move_vals)

                    records.write({
                        'import_state': 'created' if not manufacturing_check else 'updated',
                        'import_message': 'success',
                        'odoo_product_id': processed_product.product_tmpl_id.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(reference_nbr, 'kit_assembly')
            except Exception as e:
                error += len(records) or 1
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    records[:1] or self,
                    [str(e)],
                    api_acumatica='kit_assembly',
                    operation_type='manufacturing',
                    origin=reference_nbr,
                    location=header.warehouse if header else False,
                    location_dest=header.location if header else False,
                    scheduled_date=header.requested_on if header else False,
                    total_qty=header.quantity if header else 0.0,
                    payload={'header': header.read()[0] if header and header.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.stock_inventory_id or line.inventory_id or False,
                        'product_name': line.line_inventory_id or line.description or False,
                        'qty': line.line_quantity or line.quantity,
                        'uom': line.line_uom or line.uom or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in (component_lines if component_lines else records)],
                )
                records.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': str(e)[:200],
                    'odoo_product_id': False,
                    'odoo_bom_id': False,
                })


        # picking_type = PickingType.search([
        #     ('name', '=', 'Pick Components'),
        # ], limit=1)

        # if picking_type:
        #     print(f"Found picking type for code 'mrp_operation': {picking_type.id}")

        # if not picking_type:
        #     raise UserError('Picking type Manufacture tidak ditemukan.')

        # kit_assembly_warehouse = mapping_location.search([('code', '=', header.warehouse)], limit=1)
        # print(kit_assembly_warehouse)

        # company_id = kit_assembly_warehouse.odoo_building_id.id
        # print(f"Determined company for warehouse mapping: {kit_assembly_warehouse.odoo_building_id.id if kit_assembly_warehouse and kit_assembly_warehouse.odoo_building_id else 'None'}")

        # product_id = self.env['product.product'].search([
        #         ('product_tmpl_id', '=', processed_product.id),
        #     ], limit=1)

        # print(product_id)


        # vals = {
        #         'product_id': product_id.id,
        #         'product_uom_id': processed_product.uom_id.id,
        #         # 'picking_type_id': picking_type.id,  # Replace with actual picking type ID if needed
        #         'location_src_id': (
        #             kit_assembly_warehouse.odoo_location_id.id
        #             if kit_assembly_warehouse and kit_assembly_warehouse.odoo_location_id
        #             else False
        #         ),

        #         # 'location_dest_id': (
        #         #     kit_assembly_warehouse.odoo_location_id.id
        #         #     if kit_assembly_warehouse and kit_assembly_warehouse.odoo_location_id
        #         #     else False
        #         # ),
        #         # 'bom_id' : Bom.id,
        #         # 'location_final_id': False,  # Replace with actual final location ID if needed
        #         'user_id': self.env.uid,
        #         'company_id': company_id, #ambil dari company aditya
        #         'procurement_group_id': False,
        #         'orderpoint_id': False,
        #         'production_location_id': False,
        #         'create_uid': False,
        #         'write_uid': False,
        #         'name': False,
        #         'priority': False,
        #         'origin': header.name,
        #         'product_qty': header.quantity,
        #         'qty_producing': header.quantity,
        #         'date_deadline': False,
        #         'date_start': fields.Datetime.now(),
        #         'date_finished': False,
        #         'create_date': fields.Datetime.now(),
        #         'write_date': fields.Datetime.now(),
        #         'product_uom_qty': False,
        #     }

        # if manufacturing_check:
        #     print("Create MO Skipped")
        # if not manufacturing_check:
        #     if kit_assembly_warehouse.odoo_location_id.id:
        #         manufacturing = manufacturing.create(vals)
        #         print(f"Created : {manufacturing}")

        #     if not kit_assembly_warehouse.odoo_location_id.id:
        #         print('created skipped cause location not found')


# Block Kode Generate 1-Step Transfer Pemindahan barang dari penyimpanan ke Assembly Line
        # operation_type = self.env['stock.picking.type'].search([('code', '=', 'internal'), ('name', '=', 'Pick Components')], limit=1)

        # total_moving_qty = 0

        # component = component_reference.search([('assembly_id', '=', header.id)])
        # for item in component:
        #     total_moving_qty += item.line_quantity

        # vals = {
        #     'picking_type_id' : operation_type.id,
        #     'location_id' : operation_type.default_location_src_id.id,
        #     'location_dest_id' : operation_type.default_location_dest_id.id,
        #     'scheduled_date' : fields.Datetime.now(),
        #     'origin' : header.name,
        #     'adt_type' : "1-Step",
        #     'adt_total_qty' : total_moving_qty,
        # }
        # if operation_type.default_location_dest_id.usage == 'customer':
        #     raise UserError('Location tujuan customer hanya boleh dipakai oleh SO Shipment.')

        # if manufacturing_check:
        #     print("Create MO Skipped")
        # if not manufacturing_check:
        #     if kit_assembly_warehouse.odoo_location_id.id:
        #         # stock_picking = self.env['stock.picking']
        #         stock_picking = stock_picking.create(vals)
        #         print(stock_picking.name)

        #     if not kit_assembly_warehouse.odoo_location_id.id:
        #         print('created skipped cause location not found')

        # for item in component:
        #     component = self.env['product.template'].search(
        #         [('default_code', '=', item.stock_inventory_id)],
        #         limit=1
        #     )

        #     vals = {
        #             'name' : stock_picking.name,
        #             'product_id' : component.id,
        #             'product_uom_qty' : item.line_quantity,
        #             'product_uom' : component.uom_id.id,
        #             'picking_id' : stock_picking.id
        #         }

        #     if manufacturing_check:
        #         print("Create MO Skipped")
        #     if not manufacturing_check:
        #         if kit_assembly_warehouse.odoo_location_id.id:
        #             stock_move = self.env['stock.move']
        #             stock_move = stock_move.create(vals)

        #         if not kit_assembly_warehouse.odoo_location_id.id:
        #             print('created skipped cause location not found')

        msg = f'Import selesai: {created} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Receipt',
                'message': msg,
                'type': 'success' if error == 0 else 'danger',
                'sticky': True,
            }
        }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'staged',
            'import_message': False,
        })

    def action_open_product(self):
        self.ensure_one()
        if not self.odoo_product_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id':    self.odoo_product_id.id,
            'view_mode': 'form',
        }
