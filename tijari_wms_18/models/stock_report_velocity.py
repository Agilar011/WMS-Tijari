from odoo import fields, models


class StockReportFastLine(models.Model):
    _name = 'stock.report.velocity.line'
    _description = 'Fast & Slow Moving Report Line'
    _order = 'qty_out desc, id desc'

    product_id = fields.Many2one('product.product', readonly=True)
    product_name = fields.Char(readonly=True)
    qty_out = fields.Float(readonly=True)
    move_frequency = fields.Integer(readonly=True)
    last_movement_date = fields.Datetime(readonly=True)
    movement_category = fields.Selection([
        ('FAST MOVING', 'FAST MOVING'),
        ('MEDIUM MOVING', 'MEDIUM MOVING'),
        ('SLOW MOVING', 'SLOW MOVING'),
    ], readonly=True)
    generated_at = fields.Datetime(readonly=True)


class StockReportFastGenerate(models.TransientModel):
    _name = 'stock.report.velocity.generate'
    _description = 'Generate Fast & Slow Moving Report'

    analysis_days = fields.Integer(default=90, required=True)

    def action_generate_report(self):
        self.ensure_one()
        line_model = self.env['stock.report.velocity.line']
        line_model.search([]).unlink()

        query = """
            SELECT
                pp.id AS product_id,
                COALESCE(pt.name->>'en_US', pt.name->>'id_ID', 'Unknown Product') AS product_name,
                SUM(
                    CASE
                        WHEN sml.location_id != sml.location_dest_id
                             AND dest.usage = 'customer'
                        THEN sml.quantity
                        ELSE 0
                    END
                ) AS qty_out,
                COUNT(
                    CASE
                        WHEN dest.usage = 'customer' THEN 1
                    END
                ) AS move_frequency,
                MAX(sml.date) AS last_movement_date,
                CASE
                    WHEN SUM(CASE WHEN dest.usage = 'customer' THEN sml.quantity ELSE 0 END) >= 100 THEN 'FAST MOVING'
                    WHEN SUM(CASE WHEN dest.usage = 'customer' THEN sml.quantity ELSE 0 END) BETWEEN 20 AND 99 THEN 'MEDIUM MOVING'
                    ELSE 'SLOW MOVING'
                END AS movement_category
            FROM stock_move_line sml
            JOIN product_product pp ON sml.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            JOIN stock_location dest ON sml.location_dest_id = dest.id
            WHERE sml.state = 'done'
              AND sml.date >= (CURRENT_DATE - (%s || ' days')::INTERVAL)
            GROUP BY pp.id, pt.name
            ORDER BY qty_out DESC
        """
        self.env.cr.execute(query, (self.analysis_days,))
        rows = self.env.cr.dictfetchall()
        generated_at = fields.Datetime.now()

        vals_list = []
        for row in rows:
            vals_list.append({
                'product_id': row['product_id'],
                'product_name': row['product_name'],
                'qty_out': row['qty_out'] or 0.0,
                'move_frequency': row['move_frequency'] or 0,
                'last_movement_date': row['last_movement_date'],
                'movement_category': row['movement_category'] or 'SLOW MOVING',
                'generated_at': generated_at,
            })

        if vals_list:
            line_model.create(vals_list)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Report Fast & Slow Moving',
            'res_model': 'stock.report.velocity.line',
            'view_mode': 'list,form',
            'target': 'current',
        }
