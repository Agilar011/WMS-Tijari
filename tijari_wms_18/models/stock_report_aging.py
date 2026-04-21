from odoo import fields, models


class StockReportAgingLine(models.Model):
    _name = 'stock.report.aging.line'
    _description = 'Stock Aging Report Line'
    _order = 'product_id, receipt_date desc, id desc'

    product_id = fields.Many2one('product.product', readonly=True)
    product_name = fields.Char(readonly=True)
    receipt_date = fields.Datetime(readonly=True)
    layer_qty = fields.Float(readonly=True)
    aging_days = fields.Integer(readonly=True)
    aging_bucket = fields.Selection([
        ('0-30 Days', '0-30 Days'),
        ('31-60 Days', '31-60 Days'),
        ('61-90 Days', '61-90 Days'),
        ('>90 Days', '>90 Days'),
    ], readonly=True)
    generated_at = fields.Datetime(readonly=True)


class StockReportAgingGenerate(models.TransientModel):
    _name = 'stock.report.aging.generate'
    _description = 'Generate Stock Aging Report'

    def action_generate_report(self):
        self.ensure_one()
        line_model = self.env['stock.report.aging.line']
        line_model.search([]).unlink()

        query = """
            WITH moves AS (
                SELECT
                    sml.id,
                    sml.product_id,
                    sml.date,
                    CASE
                        WHEN dest.usage = 'internal' THEN sml.quantity
                        WHEN src.usage = 'internal' THEN -sml.quantity
                        ELSE 0
                    END AS qty
                FROM stock_move_line sml
                JOIN stock_location src ON sml.location_id = src.id
                JOIN stock_location dest ON sml.location_dest_id = dest.id
                WHERE sml.state = 'done'
            ),
            running AS (
                SELECT
                    *,
                    SUM(qty) OVER (
                        PARTITION BY product_id
                        ORDER BY date DESC, id DESC
                    ) AS cumulative_qty
                FROM moves
            ),
            final_balance AS (
                SELECT
                    product_id,
                    SUM(qty) AS balance_qty
                FROM moves
                GROUP BY product_id
                HAVING SUM(qty) > 0
            )
            SELECT
                fb.product_id,
                COALESCE(pt.name->>'en_US', pt.name->>'id_ID', 'Unknown Product') AS product_name,
                r.date AS receipt_date,
                CASE
                    WHEN r.cumulative_qty <= fb.balance_qty THEN r.qty
                    ELSE GREATEST(0, fb.balance_qty - (r.cumulative_qty - r.qty))
                END AS layer_qty,
                CURRENT_DATE - r.date::DATE AS aging_days,
                CASE
                    WHEN CURRENT_DATE - r.date::DATE <= 30 THEN '0-30 Days'
                    WHEN CURRENT_DATE - r.date::DATE <= 60 THEN '31-60 Days'
                    WHEN CURRENT_DATE - r.date::DATE <= 90 THEN '61-90 Days'
                    ELSE '>90 Days'
                END AS aging_bucket
            FROM running r
            JOIN final_balance fb ON r.product_id = fb.product_id
            JOIN product_product pp ON r.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE r.qty > 0
              AND r.cumulative_qty - r.qty < fb.balance_qty
            ORDER BY fb.product_id, r.date DESC
        """
        self.env.cr.execute(query)
        rows = self.env.cr.dictfetchall()
        generated_at = fields.Datetime.now()

        vals_list = []
        for row in rows:
            vals_list.append({
                'product_id': row['product_id'],
                'product_name': row['product_name'],
                'receipt_date': row['receipt_date'],
                'layer_qty': row['layer_qty'] or 0.0,
                'aging_days': row['aging_days'] or 0,
                'aging_bucket': row['aging_bucket'] or '>90 Days',
                'generated_at': generated_at,
            })

        if vals_list:
            line_model.create(vals_list)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Report Aging',
            'res_model': 'stock.report.aging.line',
            'view_mode': 'list,form',
            'target': 'current',
        }
