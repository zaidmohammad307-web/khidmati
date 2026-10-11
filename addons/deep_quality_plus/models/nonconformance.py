from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, require_role
from odoo.exceptions import AccessError, UserError


class Nonconformance(models.Model):
    _name = "deep.nonconformance"
    _description = "Nonconformance / Containment / CAPA"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    production_id = fields.Many2one("mrp.production", check_company=True, index=True)
    unit_id = fields.Many2one("deep.production.unit", check_company=True, index=True)
    session_id = fields.Many2one("deep.quality.session", check_company=True, ondelete="restrict")
    rework_id = fields.Many2one("deep.rework.order", check_company=True)
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    due_date = fields.Date(required=True, default=fields.Date.context_today)
    severity = fields.Selection(
        [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="major",
        required=True,
    )
    blocking = fields.Boolean(
        help="Blocks release and outbound shipment until QA verifies closure."
    )
    description = fields.Text(required=True)
    containment = fields.Text()
    root_cause = fields.Text()
    verification = fields.Text()
    verified_by = fields.Many2one("res.users", readonly=True)
    closed_at = fields.Datetime(readonly=True)
    action_ids = fields.One2many("deep.capa.action", "case_id")
    attachment_ids = fields.Many2many("ir.attachment")
    state = fields.Selection(
        [
            (key, key.title())
            for key in [
                "draft",
                "containment",
                "investigation",
                "actions",
                "verification",
                "closed",
            ]
        ],
        default="draft",
    )
    _session = models.Constraint(
        "UNIQUE(session_id)", "This failed session already has a nonconformance case."
    )
    _protected_fields = {"state", "verified_by", "closed_at"}

    @api.constrains("unit_id", "production_id", "session_id", "rework_id", "blocking")
    def _links(self):
        for case in self:
            if case.blocking and not (case.unit_id or case.production_id):
                raise UserError("A blocking case needs an MO or serial unit to hold.")
            if (
                case.unit_id
                and case.production_id
                and case.unit_id.production_id != case.production_id
            ):
                raise UserError("Case unit belongs to another MO.")
            if case.session_id and case.unit_id != case.session_id.unit_id:
                raise UserError("Case test session belongs to another unit.")
            if case.rework_id and case.unit_id != case.rework_id.unit_id:
                raise UserError("Case repair belongs to another unit.")

    def write(self, values):
        if any(case.state != "draft" for case in self) and set(values) & {
            "company_id",
            "unit_id",
            "session_id",
            "production_id",
            "rework_id",
        }:
            raise AccessError("Active case genealogy is immutable.")
        if "blocking" in values:
            require_role(self.env, "qa", "manager")
        return super().write(values)

    def action_contain(self):
        require_role(self.env, "qa", "manager")
        if any(not case.containment for case in self):
            raise UserError("Record the containment action.")
        return self._transition(["draft"], "containment")

    def action_investigate(self):
        require_role(self.env, "qa", "manager")
        return self._transition(["containment"], "investigation")

    def action_actions(self):
        require_role(self.env, "qa", "manager")
        if any(not case.root_cause or not case.action_ids for case in self):
            raise UserError("Record root cause and at least one corrective/preventive action.")
        return self._transition(["investigation"], "actions")

    def action_verify(self):
        require_role(self.env, "qa", "manager")
        if any(any(action.state != "done" for action in case.action_ids) for case in self):
            raise UserError("Complete every CAPA action before verification.")
        return self._transition(["actions"], "verification")

    def action_close(self):
        require_role(self.env, "qa", "manager")
        for case in self:
            if not case.action_ids or any(action.state != "done" for action in case.action_ids):
                raise UserError("Complete every CAPA action before closure.")
            if not case.verification:
                raise UserError("Record effectiveness verification before closure.")
            internal(case).write({"verified_by": self.env.uid, "closed_at": fields.Datetime.now()})
        return self._transition(["verification"], "closed", "QA verified CAPA effectiveness")


class CapaAction(models.Model):
    _name = "deep.capa.action"
    _description = "Assigned Corrective / Preventive Action"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    case_id = fields.Many2one(
        "deep.nonconformance", required=True, ondelete="restrict", check_company=True
    )
    category = fields.Selection(
        [("corrective", "Corrective"), ("preventive", "Preventive")],
        default="corrective",
        required=True,
    )
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    due_date = fields.Date(required=True, default=fields.Date.context_today)
    completion_note = fields.Text()
    completed_at = fields.Datetime(readonly=True)
    state = fields.Selection([("draft", "Open"), ("done", "Done")], default="draft")
    _protected_fields = {"state", "completed_at"}

    @api.model_create_multi
    def create(self, values):
        cases = self.env["deep.nonconformance"].browse([value["case_id"] for value in values])
        if any(case.state == "closed" for case in cases):
            raise AccessError("Closed CAPA genealogy cannot be changed.")
        return super().create(values)

    def write(self, values):
        if any(action.case_id.state == "closed" for action in self):
            raise AccessError("Closed CAPA genealogy cannot be changed.")
        return super().write(values)

    def action_done(self):
        require_role(self.env, "qa", "technician", "supervisor", "manager")
        for action in self:
            if (
                action.owner_id != self.env.user
                and not self.env.su
                and not self.env.user.has_group("deep_core.group_manager")
            ):
                raise AccessError("Only the assigned owner may complete this action.")
            if not action.completion_note:
                raise UserError("Record completion evidence.")
            internal(action).write({"completed_at": fields.Datetime.now()})
        return self._transition(["draft"], "done")
