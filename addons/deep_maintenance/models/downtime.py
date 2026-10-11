from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_role
from odoo.exceptions import AccessError, UserError


class Reason(models.Model):
    _name = "deep.downtime.reason"
    _description = "Machine Downtime Reason"
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    planned = fields.Boolean()
    active = fields.Boolean(default=True)
    _code = models.Constraint("UNIQUE(company_id,code)", "Downtime code already exists.")


class Downtime(models.Model):
    _name = "deep.downtime.event"
    _description = "Work Center Downtime / Breakdown"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    workcenter_id = fields.Many2one("mrp.workcenter", required=True, check_company=True, index=True)
    workorder_id = fields.Many2one("mrp.workorder", check_company=True)
    reason_id = fields.Many2one("deep.downtime.reason", required=True, check_company=True)
    equipment_id = fields.Many2one("maintenance.equipment", check_company=True)
    maintenance_team_id = fields.Many2one("maintenance.team", required=True, check_company=True)
    technician_id = fields.Many2one("res.users")
    start = fields.Datetime(default=fields.Datetime.now, required=True)
    expected_end = fields.Datetime(required=True)
    end = fields.Datetime(readonly=True)
    duration_hours = fields.Float(compute="_duration")
    root_cause = fields.Text()
    corrective_action = fields.Text()
    block_starts = fields.Boolean(default=True)
    leave_id = fields.Many2one("resource.calendar.leaves", readonly=True)
    request_id = fields.Many2one("maintenance.request", readonly=True, check_company=True)
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "open", "closed"]], default="draft"
    )
    _interval = models.Constraint(
        'CHECK(expected_end>start AND ("end" IS NULL OR "end">=start))',
        "Invalid downtime interval.",
    )
    _protected_fields = {"state", "leave_id", "request_id", "end"}

    @api.constrains("workorder_id", "workcenter_id")
    def _center(self):
        for event in self:
            if event.workorder_id and event.workorder_id.workcenter_id != event.workcenter_id:
                raise UserError("Downtime work order belongs to another center.")

    def write(self, values):
        if any(event.state == "open" for event in self) and set(values) & {
            "company_id",
            "workcenter_id",
            "workorder_id",
            "start",
            "reason_id",
            "block_starts",
        }:
            raise AccessError("Started downtime identity is frozen.")
        result = super().write(values)
        if "expected_end" in values:
            for event in self.filtered(lambda record: record.state == "open" and record.leave_id):
                event.leave_id.sudo().date_to = event.expected_end
        return result

    @api.depends("start", "end", "state")
    def _duration(self):
        for event in self:
            finish = event.end or fields.Datetime.now()
            event.duration_hours = (
                max(0, (finish - event.start).total_seconds() / 3600) if event.start else 0
            )

    def action_start(self):
        require_role(self.env, "operator", "technician", "supervisor", "manager")
        for event in self:
            lock(event.workcenter_id)
            if event.state != "draft":
                raise UserError("Start a new draft downtime record.")
            if event.start > fields.Datetime.now():
                raise UserError(
                    "Use preventive scheduling for future maintenance; actual downtime cannot start in the future."
                )
            if event.block_starts and self.search_count(
                [
                    ("id", "!=", event.id),
                    ("workcenter_id", "=", event.workcenter_id.id),
                    ("state", "=", "open"),
                    ("block_starts", "=", True),
                ]
            ):
                raise UserError("The center already has an open blocking downtime record.")
            values = {}
            if event.block_starts:
                leave = (
                    self.env["resource.calendar.leaves"]
                    .sudo()
                    .create(
                        {
                            "name": event.name,
                            "calendar_id": event.workcenter_id.resource_calendar_id.id,
                            "resource_id": event.workcenter_id.resource_id.id,
                            "date_from": event.start,
                            "date_to": event.expected_end,
                            "time_type": "leave",
                        }
                    )
                )
                values["leave_id"] = leave.id
            request = self.env["maintenance.request"].create(
                {
                    "name": event.name,
                    "company_id": event.company_id.id,
                    "equipment_id": event.equipment_id.id,
                    "maintenance_team_id": event.maintenance_team_id.id,
                    "user_id": event.technician_id.id,
                    "maintenance_type": "corrective",
                    "schedule_date": event.start,
                    "deep_workcenter_id": event.workcenter_id.id,
                    "deep_downtime_id": event.id,
                }
            )
            values["request_id"] = request.id
            internal(event).write(values)
        return self._transition(
            ["draft"], "open", "Native calendar interruption and maintenance request recorded"
        )

    def action_close(self):
        require_role(self.env, "technician", "supervisor", "manager")
        for event in self:
            lock(event)
            if not event.root_cause or not event.corrective_action:
                raise UserError("Record root cause and corrective action before restart.")
            if (
                event.technician_id
                and event.technician_id != self.env.user
                and not self.env.su
                and not self.env.user.has_group("deep_core.group_supervisor")
                and not self.env.user.has_group("deep_core.group_manager")
            ):
                raise AccessError("Only the assigned technician may close this breakdown.")
            now = fields.Datetime.now()
            if event.start > now:
                raise UserError("Downtime start cannot be after completion.")
            if event.leave_id:
                # Native calendars require a positive interval.
                from datetime import timedelta

                event.leave_id.sudo().date_to = max(now, event.start + timedelta(seconds=1))
            done_stage = self.env["maintenance.stage"].search([("done", "=", True)], limit=1)
            if done_stage and event.request_id:
                event.request_id.write(
                    {"stage_id": done_stage.id, "close_date": fields.Date.today()}
                )
            internal(event).write({"end": now})
        return self._transition(
            ["open"], "closed", "Maintenance closure authorizes work center restart"
        )
