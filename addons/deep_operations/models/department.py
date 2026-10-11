from odoo import fields, models


class Department(models.Model):
    _name = "deep.production.department"
    _description = "Production Department"
    _check_company_auto = True
    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    supervisor_id = fields.Many2one("res.users")
    workcenter_ids = fields.One2many("mrp.workcenter", "deep_department_id")
    active = fields.Boolean(default=True)
    _code = models.Constraint("UNIQUE(company_id,code)", "Department code must be unique.")


class Workcenter(models.Model):
    _inherit = "mrp.workcenter"
    deep_department_id = fields.Many2one(
        "deep.production.department", check_company=True, index=True
    )
