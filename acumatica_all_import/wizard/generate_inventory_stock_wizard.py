from odoo import fields, models, _
from odoo.exceptions import UserError


class AcumaticaInventoryStockGenerateWizard(models.TransientModel):
    _name = "acumatica.inventory.stock.generate.wizard"
    _description = "Generate Data Stock ERP"

    location_mapping_ids = fields.Many2many(
        "stock.location.acumatica",
        "acum_stock_gen_loc_rel",
        "wizard_id",
        "location_id",
        string="Location Mapping",
        required=True,
        domain=[("active", "=", True)],
    )

    def action_generate(self):
        self.ensure_one()
        config = self.env["acumatica.config"].sudo().search(
            [("config_type", "=", "inventory_stock"), ("active", "=", True)],
            order="is_default desc, id",
            limit=1,
        )
        if not config:
            raise UserError(_("Konfigurasi API Inventory Stock tidak ditemukan."))

        mappings = self.location_mapping_ids.filtered("code")
        if not mappings:
            raise UserError(_("Mapping yang dipilih belum memiliki Warehouse Code."))

        ImportWizard = self.env["import.inventory.stock.wizard"].sudo()
        for mapping in mappings:
            fetch_wizard = ImportWizard.create({
                "config_id": config.id,
                "warehouse_value": mapping.code,
                "inventory_id_value": (
                    config.request_inventory_id_value
                    if "request_inventory_id_value" in config._fields
                    else False
                ),
                "odata_expand": config.odata_expand or "InventorySiteInquiryDetails",
                "odata_top": (
                    config.odata_top
                    if "odata_top" in config._fields and config.odata_top
                    else 0
                ),
            })
            fetch_wizard.action_fetch_data()

        action = self.env.ref(
            "acumatica_all_import.action_acumatica_inventory_stock_quant"
        ).sudo().read()[0]
        action["domain"] = [("warehouse_code", "in", mappings.mapped("code"))]
        return action
