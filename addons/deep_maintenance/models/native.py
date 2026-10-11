from odoo import fields, models
from odoo.exceptions import UserError


class MaintenanceRequest(models.Model):
    _inherit = "maintenance.request"
    deep_workcenter_id = fields.Many2one("mrp.workcenter", check_company=True)
    deep_downtime_id = fields.Many2one("deep.downtime.event", check_company=True, index=True)
    deep_preventive_plan_id = fields.Many2one("deep.preventive.plan", check_company=True)
    deep_due_date = fields.Date(index=True)
    _preventive = models.Constraint(
        "UNIQUE(deep_preventive_plan_id,deep_due_date)",
        "Preventive request already exists for this due date.",
    )


class Workcenter(models.Model):
    _inherit = "mrp.workcenter"
    deep_equipment_id = fields.Many2one("maintenance.equipment", check_company=True)


class Workorder(models.Model):
    _inherit = "mrp.workorder"

    def _deep_downtime_check(self):
        for work in self:
            if self.env["deep.downtime.event"].search_count(
                [
                    ("workcenter_id", "=", work.workcenter_id.id),
                    ("company_id", "=", work.company_id.id),
                    ("state", "=", "open"),
                    ("block_starts", "=", True),
                ],
                limit=1,
            ):
                raise UserError("This work center has an open blocking downtime record.")

    def write(self, values):
        if values.get("state") in ("progress", "done"):
            self._deep_downtime_check()
        return super().write(values)

    def button_start(self, *args, **kwargs):
        self._deep_downtime_check()
        return super().button_start(*args, **kwargs)

    def button_finish(self, *args, **kwargs):
        self._deep_downtime_check()
        return super().button_finish(*args, **kwargs)
