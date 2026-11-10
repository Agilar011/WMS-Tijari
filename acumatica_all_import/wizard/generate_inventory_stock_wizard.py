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

        ungrouped = []
        for mapping in mappings:
            location = mapping.odoo_location_id
            has_group = bool(location and (location.location_group_id or location.is_location_mapping))
            parent = location.location_id if location else self.env["stock.location"]
            while parent and not has_group:
                has_group = parent.is_location_mapping
                parent = parent.location_id
            if not has_group:
                ungrouped.append(mapping.display_name)
        if ungrouped:
            raise UserError(_(
                "Lokasi berikut belum memiliki group: %(locations)s",
                locations=", ".join(ungrouped),
            ))

        Job = self.env["acumatica.inventory.stock.generate.job"].sudo()
        queued = Job.browse()
        for mapping in mappings:
            active_job = Job.search([
                ("config_id", "=", config.id),
                ("location_mapping_id", "=", mapping.id),
                ("state", "in", ("queued", "running")),
            ], limit=1)
            queued |= active_job or Job.create({
                "config_id": config.id,
                "location_mapping_id": mapping.id,
                "requested_by_id": self.env.user.id,
            })

        cron = self.env.ref(
            "acumatica_all_import.ir_cron_inventory_stock_generate_jobs",
            raise_if_not_found=False,
        )
        if cron:
            cron._trigger()

        action = self.env.ref(
            "acumatica_all_import.action_inventory_stock_generate_job"
        ).sudo().read()[0]
        action["domain"] = [("id", "in", queued.ids)]
        return action
