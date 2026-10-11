from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_internal, require_role


class PreventivePlan(models.Model):
    _name = "deep.preventive.plan"
    _description = "Recurring Preventive Maintenance Schedule"
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    equipment_id = fields.Many2one("maintenance.equipment", required=True, check_company=True)
    workcenter_id = fields.Many2one("mrp.workcenter", check_company=True)
    maintenance_team_id = fields.Many2one("maintenance.team", required=True, check_company=True)
    technician_id = fields.Many2one("res.users")
    interval_days = fields.Integer(default=30, required=True)
    next_date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    last_request_id = fields.Many2one("maintenance.request", readonly=True, check_company=True)
    instructions = fields.Html(sanitize=True)
    active = fields.Boolean(default=True)
    _interval = models.Constraint(
        "CHECK(interval_days>0)", "Maintenance interval must be positive."
    )

    @api.model_create_multi
    def create(self, values):
        if any(value.get("last_request_id") for value in values):
            require_internal(self.env)
        return super().create(values)

    def write(self, values):
        if "last_request_id" in values:
            require_internal(self.env)
        return super().write(values)

    def action_generate(self):
        require_role(self.env, "technician", "supervisor", "manager")
        for plan in self:
            lock(plan)
            due = plan.next_date
            existing = self.env["maintenance.request"].search(
                [("deep_preventive_plan_id", "=", plan.id), ("deep_due_date", "=", due)], limit=1
            )
            request = existing or self.env["maintenance.request"].create(
                {
                    "name": plan.name + " / " + str(due),
                    "company_id": plan.company_id.id,
                    "equipment_id": plan.equipment_id.id,
                    "maintenance_team_id": plan.maintenance_team_id.id,
                    "user_id": plan.technician_id.id,
                    "maintenance_type": "preventive",
                    "schedule_date": str(due) + " 08:00:00",
                    "description": plan.instructions,
                    "deep_workcenter_id": plan.workcenter_id.id,
                    "deep_preventive_plan_id": plan.id,
                    "deep_due_date": due,
                }
            )
            internal(plan).write(
                {
                    "last_request_id": request.id,
                    "next_date": due + timedelta(days=plan.interval_days),
                }
            )
            self.env["deep.audit.event"]._record(
                plan, "preventive_request_created", reason=request.name
            )
        return True

    def _cron_generate(self):
        self.search(
            [("active", "=", True), ("next_date", "<=", fields.Date.today())], limit=100
        ).action_generate()
