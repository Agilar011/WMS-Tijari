# -*- coding: utf-8 -*-
from odoo import models


class AcumaticaPickingTypeReresolveMixin(models.AbstractModel):
    """Cari ulang picking type staging memakai resolver import wizard.

    Staging bisa masuk tanpa picking type (lewat webhook, atau resolver gagal saat
    fetch). Saat import, picking type dicari ulang dengan resolver wizard yang sama
    persis seperti saat fetch. Hasilnya TIDAK ditulis ke staging — cuma dipakai
    untuk membuat dokumen WMS.
    """
    _name = 'acumatica.picking.type.reresolve.mixin'
    _description = 'Cari Ulang Picking Type Staging Acumatica'

    def _adt_picking_type_wizard_call(self):
        """Override per model.

        Kembalikan ``(nama_wizard, args, kwargs)`` persis seperti wizard memanggil
        ``_search_picking_type`` saat fetch, atau ``False`` bila wizard juga tidak
        memanggil resolver untuk record ini.
        """
        return False

    def _adt_reresolve_picking_type(self):
        """Picking type staging bila terisi; bila kosong, cari ulang via wizard."""
        self.ensure_one()
        PickingType = self.env['stock.picking.type']
        if self.picking_type_id:
            return self.picking_type_id

        call = self._adt_picking_type_wizard_call()
        if not call:
            return PickingType
        wizard_name, args, kwargs = call

        Wizard = self.env[wizard_name]
        vals = {}
        if 'config_id' in Wizard._fields and 'config_id' in self._fields and self.config_id:
            vals['config_id'] = self.config_id.id
        # new() = record di memori, tidak membuat baris wizard di database
        result = Wizard.new(vals)._search_picking_type(*args, **kwargs)

        # import.inventory.issue.wizard mengembalikan (picking_type, warehouse_code)
        if isinstance(result, tuple):
            result = result[0]
        return result or PickingType
