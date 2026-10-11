from odoo import api, fields, models
from odoo.addons.deep_core.security import lock, require_role
from odoo.addons.deep_core.services.export import export_xlsx
from odoo.exceptions import UserError

from ..services.capacity import CapacityService


class Snapshot(models.Model):
    _name = "deep.capacity.snapshot"
    _inherit = "deep.service.result"
    _description = "Machine and Qualified Labor Capacity"
    _check_company_auto = True
    plan_id = fields.Many2one("deep.mps.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True)
    period_id = fields.Many2one("deep.mps.period", required=True, ondelete="cascade")
    workcenter_id = fields.Many2one("mrp.workcenter", required=True, check_company=True)
    available_hours = fields.Float()
    required_hours = fields.Float()
    labor_hours = fields.Float()
    qualified_hours = fields.Float()
    labor_shortage = fields.Boolean()
    unavailable = fields.Boolean(compute="_load", store=True)
    utilization = fields.Float(compute="_load", store=True)
    overload_hours = fields.Float(compute="_load", store=True)
    at = fields.Datetime(default=fields.Datetime.now)

    @api.depends("available_hours", "required_hours")
    def _load(self):
        for r in self:
            r.unavailable = not r.available_hours and r.required_hours > 0
            r.utilization = r.required_hours / r.available_hours * 100 if r.available_hours else 0
            r.overload_hours = max(0, r.required_hours - r.available_hours)

    def action_export(self):
        return export_xlsx(
            self,
            "Capacity.xlsx",
            [
                "Work Center",
                "Period",
                "Available h",
                "Required h",
                "Load %",
                "Overload h",
                "Labor h",
                "Qualified h",
                "Labor Shortage",
            ],
            [
                [
                    r.workcenter_id.name,
                    r.period_id.name,
                    r.available_hours,
                    r.required_hours,
                    r.utilization,
                    r.overload_hours,
                    r.labor_hours,
                    r.qualified_hours,
                    r.labor_shortage,
                ]
                for r in self
            ],
        )


class Plan(models.Model):
    _inherit = "deep.mps.plan"
    capacity_ids = fields.One2many("deep.capacity.snapshot", "plan_id", readonly=True)

    def action_capacity(self):
        require_role(self.env, "planner", "manager")
        for p in self:
            lock(p)
            if not p.calculated_at:
                raise UserError("Calculate MPS first.")
            if p.state not in ("draft", "reviewed"):
                raise UserError("Approved capacity snapshots are frozen.")
            CapacityService(self.env).calculate(p)
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.capacity.snapshot",
            "view_mode": "list,pivot,graph",
            "domain": [("plan_id", "in", self.ids)],
        }

    def action_calculate(self):
        result = super().action_calculate()
        for p in self:
            CapacityService(self.env).calculate(p)
        return result
