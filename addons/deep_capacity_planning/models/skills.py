from odoo import api, fields, models
from odoo.exceptions import ValidationError


class Skill(models.Model):
    _name = "deep.skill"
    _description = "Manufacturing Skill"
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)


class Level(models.Model):
    _name = "deep.skill.level"
    _description = "Qualification Level"
    _order = "rank"
    name = fields.Char(required=True)
    rank = fields.Integer(required=True, default=1)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    _rank = models.Constraint("CHECK(rank>0)", "Qualification rank must be positive.")


class EmployeeSkill(models.Model):
    _name = "deep.employee.skill"
    _description = "Employee Qualification"
    _check_company_auto = True
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    employee_id = fields.Many2one("hr.employee", required=True, check_company=True)
    skill_id = fields.Many2one("deep.skill", required=True, check_company=True)
    level_id = fields.Many2one("deep.skill.level", required=True, check_company=True)
    valid_until = fields.Date()
    _unique = models.Constraint("UNIQUE(employee_id,skill_id)", "Duplicate employee qualification.")


class Requirement(models.Model):
    _name = "deep.operation.skill"
    _description = "Operation Skill Requirement"
    _check_company_auto = True
    operation_id = fields.Many2one("mrp.routing.workcenter", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="operation_id.company_id", store=True)
    skill_id = fields.Many2one("deep.skill", required=True, check_company=True)
    level_id = fields.Many2one("deep.skill.level", required=True, check_company=True)
    operator_count = fields.Integer(default=1, required=True)
    _headcount = models.Constraint(
        "CHECK(operator_count>0)", "Qualified headcount must be positive."
    )


class Shift(models.Model):
    _name = "deep.labor.shift"
    _description = "Employee Work Center Shift Allocation"
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    workcenter_id = fields.Many2one("mrp.workcenter", required=True, check_company=True)
    start = fields.Datetime(required=True, index=True)
    end = fields.Datetime(required=True)
    employee_ids = fields.Many2many("hr.employee", check_company=True)
    _interval = models.Constraint('CHECK("end">start)', "Invalid shift interval.")

    @api.constrains("start", "end", "employee_ids")
    def _overlap(self):
        for r in self:
            if self.search_count(
                [
                    ("id", "!=", r.id),
                    ("company_id", "=", r.company_id.id),
                    ("employee_ids", "in", r.employee_ids.ids),
                    ("start", "<", r.end),
                    ("end", ">", r.start),
                ]
            ):
                raise ValidationError("An employee cannot be allocated to overlapping shifts.")


class Operation(models.Model):
    _inherit = "mrp.routing.workcenter"
    deep_skill_ids = fields.One2many("deep.operation.skill", "operation_id")
