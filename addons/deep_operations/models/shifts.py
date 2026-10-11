from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, require_role
from odoo.addons.deep_core.services.export import export_xlsx
from odoo.exceptions import AccessError, UserError


class ShiftReport(models.Model):
    _name = "deep.shift.report"
    _description = "Daily Shift Production Report"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    department_id = fields.Many2one("deep.production.department", required=True, check_company=True)
    production_id = fields.Many2one("mrp.production", required=True, check_company=True, index=True)
    workorder_id = fields.Many2one("mrp.workorder", check_company=True)
    batch_id = fields.Many2one("deep.production.batch", check_company=True)
    shift_start = fields.Datetime(required=True, default=fields.Datetime.now)
    shift_end = fields.Datetime(required=True)
    operator_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    operator_count = fields.Integer(default=1, required=True)
    planned_qty = fields.Float(required=True)
    good_qty = fields.Float()
    rework_qty = fields.Float()
    scrap_qty = fields.Float()
    downtime_minutes = fields.Float()
    notes = fields.Text()
    rejection_reason = fields.Text()
    approved_by = fields.Many2one("res.users", readonly=True)
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "submitted", "approved", "rejected"]],
        default="draft",
    )
    labor_hours = fields.Float(compute="_metrics")
    attainment = fields.Float(compute="_metrics")
    quality_rate = fields.Float(compute="_metrics")
    _positive = models.Constraint(
        "CHECK(planned_qty>=0 AND good_qty>=0 AND rework_qty>=0 AND scrap_qty>=0 AND downtime_minutes>=0 AND operator_count>0)",
        "Shift values cannot be negative.",
    )
    _interval = models.Constraint("CHECK(shift_end>shift_start)", "Shift end must follow start.")
    _frozen_states = ("approved", "rejected")
    _protected_fields = {"state", "approved_by"}

    @api.constrains(
        "workorder_id",
        "production_id",
        "batch_id",
        "good_qty",
        "rework_qty",
        "scrap_qty",
        "downtime_minutes",
        "shift_start",
        "shift_end",
    )
    def _check_report(self):
        for report in self:
            if report.workorder_id and report.workorder_id.production_id != report.production_id:
                raise UserError("The work order belongs to another MO.")
            if report.batch_id and report.batch_id.production_id != report.production_id:
                raise UserError("The batch belongs to another MO.")
            duration = (report.shift_end - report.shift_start).total_seconds() / 60
            if report.downtime_minutes > duration:
                raise UserError("Downtime cannot exceed the shift duration.")
            if (
                report.good_qty + report.rework_qty + report.scrap_qty
                > report.production_id.product_qty
            ):
                raise UserError("Reported output exceeds the MO quantity.")

    @api.model_create_multi
    def create(self, values):
        if (
            not self.env.su
            and not self.env.user.has_group("deep_core.group_supervisor")
            and not self.env.user.has_group("deep_core.group_manager")
            and any(value.get("operator_id", self.env.uid) != self.env.uid for value in values)
        ):
            raise AccessError("Create only your own shift report.")
        return super().create(values)

    def write(self, values):
        if any(report.state == "submitted" for report in self) and set(values) - {
            "state",
            "approved_by",
            "rejection_reason",
        }:
            raise AccessError("Submitted report content is frozen.")
        if (
            not self.env.su
            and not self.env.user.has_group("deep_core.group_supervisor")
            and not self.env.user.has_group("deep_core.group_manager")
            and any(report.operator_id != self.env.user for report in self)
        ):
            raise AccessError("Edit only your own shift report.")
        if (
            "operator_id" in values
            and not self.env.su
            and not self.env.user.has_group("deep_core.group_supervisor")
            and not self.env.user.has_group("deep_core.group_manager")
            and values["operator_id"] != self.env.uid
        ):
            raise AccessError("Report ownership requires a supervisor.")
        return super().write(values)

    @api.depends(
        "shift_start",
        "shift_end",
        "operator_count",
        "good_qty",
        "rework_qty",
        "scrap_qty",
        "planned_qty",
    )
    def _metrics(self):
        for report in self:
            report.labor_hours = (
                (report.shift_end - report.shift_start).total_seconds()
                / 3600
                * report.operator_count
                if report.shift_start and report.shift_end
                else 0
            )
            report.attainment = (
                report.good_qty / report.planned_qty * 100 if report.planned_qty else 0
            )
            total = report.good_qty + report.rework_qty + report.scrap_qty
            report.quality_rate = report.good_qty / total * 100 if total else 0

    def action_submit(self):
        require_role(self.env, "operator", "supervisor", "manager")
        return self._transition(["draft"], "submitted")

    def action_approve(self):
        require_role(self.env, "supervisor", "manager")
        for report in self:
            if (
                not report.good_qty
                and not report.rework_qty
                and not report.scrap_qty
                and not report.notes
            ):
                raise UserError("A zero-output shift needs an explanation.")
            internal(report).write({"approved_by": self.env.uid})
        return self._transition(
            ["submitted"],
            "approved",
            "Supervisor approved reported actuals; native stock remains authoritative",
        )

    def action_reject(self):
        require_role(self.env, "supervisor", "manager")
        if any(not report.rejection_reason for report in self):
            raise UserError("Record the rejection reason.")
        return self._transition(["submitted"], "rejected")

    def action_export(self):
        return export_xlsx(
            self,
            "Shift_Reports.xlsx",
            [
                "Shift",
                "Department",
                "MO",
                "Start",
                "End",
                "Planned",
                "Reported Good",
                "Rework",
                "Scrap",
                "Downtime min",
                "Labor h",
                "State",
            ],
            [
                [
                    report.name,
                    report.department_id.name,
                    report.production_id.name,
                    str(report.shift_start),
                    str(report.shift_end),
                    report.planned_qty,
                    report.good_qty,
                    report.rework_qty,
                    report.scrap_qty,
                    report.downtime_minutes,
                    report.labor_hours,
                    report.state,
                ]
                for report in self
            ],
        )
