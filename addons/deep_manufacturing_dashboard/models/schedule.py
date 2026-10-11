from datetime import timedelta

from odoo import fields, models
from odoo.addons.deep_core.security import lock, require_role
from odoo.exceptions import UserError


class ScheduleChange(models.TransientModel):
    _name = "deep.schedule.change"
    _description = "Audited Work Order Schedule Change"
    workorder_id = fields.Many2one("mrp.workorder", required=True)
    start = fields.Datetime(required=True)
    reason = fields.Text(required=True)

    def action_apply(self):
        self.ensure_one()
        require_role(self.env, "planner", "supervisor", "manager")
        work = self.workorder_id
        lock(work)
        if work.state in ("done", "cancel", "progress"):
            raise UserError("Only unstarted operations may be rescheduled.")
        if len(self.reason.strip()) < 5:
            raise UserError("Record a meaningful scheduling reason.")
        previous = str(work.date_start)
        work.write(
            {
                "date_start": self.start,
                "date_finished": self.start + timedelta(minutes=work.duration_expected),
            }
        )
        self.env["deep.audit.event"]._record(
            work, "rescheduled", previous, str(self.start), self.reason
        )
        return {"type": "ir.actions.act_window_close"}
