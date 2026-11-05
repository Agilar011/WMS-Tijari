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
        mapped_locations = mappings.mapped("odoo_location_id")
        mapped_locations |= mappings.mapped("odoo_building_id.lot_stock_id")
        unmapped_codes = mappings.filtered(
            lambda mapping: not mapping.odoo_location_id
            and not mapping.odoo_building_id.lot_stock_id
        ).mapped("code")

        domain = [("config_id", "=", config.id)]
        if mapped_locations and unmapped_codes:
            domain.extend([
                "|",
                ("location_id", "in", mapped_locations.ids),
                ("warehouse_code", "in", unmapped_codes),
            ])
        elif mapped_locations:
            domain.append(("location_id", "in", mapped_locations.ids))
        else:
            domain.append(("warehouse_code", "in", unmapped_codes))
        action["domain"] = domain
        return action
