from odoo import api, fields, models

class ResUsers(models.Model):
    _inherit = 'res.users'

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Default Warehouse'
    )

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Allowed Warehouses'
    )


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _tijari_ensure_inventory_group_xmlid(self, xmlid_name, group_name):
        module = "tijari_wms_18"
        IrModelData = self.env['ir.model.data'].sudo()
        xmlid = IrModelData.search([
            ('module', '=', module),
            ('name', '=', xmlid_name),
        ], limit=1)
        if xmlid and xmlid.model == 'res.groups' and self.browse(xmlid.res_id).exists():
            return True
        if xmlid:
            xmlid.unlink()

        group = self.sudo().search([
            ('category_id.name', '=', 'Inventory'),
            ('name', 'in', [group_name, '%s ' % group_name]),
        ], limit=1)
        if not group:
            group = self.sudo().search([
                ('category_id.name', '=', 'Inventory'),
                ('name', 'ilike', group_name),
            ], limit=1)
        if not group:
            raise ValueError("Group Inventory / %s belum ada." % group_name)

        IrModelData.create({
            'module': module,
            'name': xmlid_name,
            'model': 'res.groups',
            'res_id': group.id,
            'noupdate': True,
        })
        return True

    @api.model
    def _tijari_ensure_picker_group_xmlid(self):
        return self._tijari_ensure_inventory_group_xmlid('group_picker', 'Picker')

    @api.model
    def _tijari_ensure_putaway_group_xmlid(self):
        return self._tijari_ensure_inventory_group_xmlid('group_putaway', 'Putaway')

    @api.model
    def _tijari_ensure_packer_group_xmlid(self):
        return self._tijari_ensure_inventory_group_xmlid('group_packer', 'Packer')
