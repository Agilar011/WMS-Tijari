from markupsafe import Markup, escape

from odoo import models


class AcumaticaImportLogMixin(models.AbstractModel):
    """Keep transaction staging chatter useful after an import.

    The import status/message fields remain the compact machine-readable result;
    this adds the human-readable audit entry used by the master-data staging
    models as well.
    """

    _name = 'acumatica.import.log.mixin'
    _description = 'Acumatica Import Chatter Log'

    def _acumatica_post_import_log(self, state, message, record=False, changed_fields=None):
        self = self.exists()
        if not self:
            return

        titles = {
            'created': '✅ Import Berhasil',
            'updated': '🔄 Data Diperbarui',
            'error': '❌ Import Gagal',
        }
        body = Markup('<p><strong>{}</strong></p><p>{}</p>').format(
            titles.get(state, 'Import Log'),
            escape(str(message or '-')).replace('\n', Markup('<br/>')),
        )

        if changed_fields:
            body += Markup('<p><strong>Perubahan:</strong></p><ul>')
            for change in changed_fields:
                body += Markup('<li><strong>{}</strong>: {} → {}</li>').format(
                    escape(str(change.get('field_label') or change.get('field_name') or '-')),
                    escape(str(change.get('old_value') or '-')),
                    escape(str(change.get('new_value') or '-')),
                )
            body += Markup('</ul>')

        if record and record.exists():
            body += Markup(
                '<p>Record Odoo: <a href="#" data-oe-model="{}" data-oe-id="{}">{}</a></p>'
            ).format(escape(record._name), record.id, escape(record.display_name))

        self.with_context(
            mail_create_nosubscribe=True,
            mail_post_autofollow=False,
        ).message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

    def _acumatica_write_import_result_once(self, records, header, vals):
        """Write a document result to its rows and post chatter only on its header."""
        records = records.exists()
        if not records:
            return True

        header = (records & header.exists())[:1] or records[:1]
        detail_records = records - header
        if detail_records:
            detail_records.with_context(skip_acumatica_import_log=True).write(vals)
        return header.with_context(skip_acumatica_import_log=False).write(vals)

    def _acumatica_search_first_by(self, model_name, field_name, values, domain=None):
        """Fetch matching records once, keeping the first record per field value."""
        values = list(dict.fromkeys(value for value in values if value))
        if not values:
            return {}

        model = self.env[model_name]
        records = model.search((domain or []) + [(field_name, 'in', values)])
        result = {}
        for record in records:
            value = record[field_name]
            result.setdefault(value, record)
        return result

    def _acumatica_import_error_state(self, error_message):
        """Classify source documents that cannot be updated after processing."""
        rejected_terms = (
            'tidak bisa diupdate',
            'update digagalkan',
            'sudah divalidasi',
            'already processed',
            'state ready',
            'state done',
            'state processed',
        )
        message = str(error_message or '').lower()
        return 'rejected' if any(term in message for term in rejected_terms) else 'error'

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get('skip_acumatica_import_log'):
            return result

        state = vals.get('import_state')
        if state in ('created', 'updated', 'error'):
            has_picking_field = 'odoo_picking_id' in self._fields
            record = self.env["stock.picking"].browse(vals.get('odoo_picking_id')) if has_picking_field and vals.get('odoo_picking_id') else (self.mapped('odoo_picking_id')[:1] if has_picking_field else self.env['stock.picking'].browse())
            message = vals.get('import_message') or {
                'created': 'Data transaksi berhasil dibuat.',
                'updated': 'Data transaksi berhasil diperbarui.',
                'error': 'Import transaksi gagal.',
            }[state]
            if state == 'updated' and record:
                message = '{} Data yang disinkronkan: header stock.picking dan detail stock.move.'.format(message)
            self._acumatica_post_import_log(state, message, record)
        return result
