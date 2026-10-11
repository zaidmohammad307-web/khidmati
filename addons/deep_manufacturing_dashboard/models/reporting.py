from odoo import fields, models, tools


class QualitySummary(models.Model):
    _name = "deep.quality.summary"
    _description = "Read Only Serial Quality Analytics"
    _auto = False
    company_id = fields.Many2one("res.company", readonly=True)
    unit_id = fields.Many2one("deep.production.unit", readonly=True)
    product_id = fields.Many2one("product.product", readonly=True)
    state = fields.Char(readonly=True)
    tested = fields.Integer(readonly=True)
    first_pass = fields.Integer(readonly=True)
    last_pass = fields.Integer(readonly=True)
    retested = fields.Integer(readonly=True)
    retest_pass = fields.Integer(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE VIEW deep_quality_summary AS
            SELECT u.id,u.company_id,u.id AS unit_id,u.product_id,u.state,
                CASE WHEN q.tests>0 THEN 1 ELSE 0 END AS tested,
                CASE WHEN q.first_outcome='pass' THEN 1 ELSE 0 END AS first_pass,
                CASE WHEN q.last_outcome='pass' THEN 1 ELSE 0 END AS last_pass,
                CASE WHEN q.tests>1 THEN 1 ELSE 0 END AS retested,
                CASE WHEN q.tests>1 AND q.last_outcome='pass' THEN 1 ELSE 0 END AS retest_pass
            FROM deep_production_unit u LEFT JOIN (
                SELECT unit_id,COUNT(*) AS tests,
                    (array_agg(outcome ORDER BY id))[1] AS first_outcome,
                    (array_agg(outcome ORDER BY id DESC))[1] AS last_outcome
                FROM deep_quality_session WHERE state='done' GROUP BY unit_id
            ) q ON q.unit_id=u.id""")
