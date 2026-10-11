from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_role


class Handover(models.Model):
    _name = "deep.wip.handover"
    _description = "Department WIP Handover / Receiver Acknowledgement"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    production_id = fields.Many2one("mrp.production", required=True, check_company=True)
    batch_id = fields.Many2one("deep.production.batch", check_company=True)
    from_department_id = fields.Many2one(
        "deep.production.department", required=True, check_company=True
    )
    to_department_id = fields.Many2one(
        "deep.production.department", required=True, check_company=True
    )
    quantity = fields.Float(required=True)
    sender_id = fields.Many2one("res.users", readonly=True)
    receiver_id = fields.Many2one("res.users", required=True)
    sent_at = fields.Datetime(readonly=True)
    received_at = fields.Datetime(readonly=True)
    transit_hours = fields.Float(compute="_duration")
    notes = fields.Text()
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "sent", "received", "rejected"]], default="draft"
    )
    _positive = models.Constraint("CHECK(quantity>0)", "Handover quantity must be positive.")
    _departments = models.Constraint(
        "CHECK(from_department_id!=to_department_id)",
        "Choose different source and receiving departments.",
    )
    _protected_fields = {"state", "sender_id", "sent_at", "received_at"}
    _frozen_states = ("received", "rejected")

    def write(self, values):
        if any(record.state == "sent" for record in self) and set(values) - {
            "state",
            "received_at",
            "notes",
        }:
            raise AccessError("Sent handover contents and assigned receiver are frozen.")
        return super().write(values)

    @api.depends("sent_at", "received_at")
    def _duration(self):
        for record in self:
            record.transit_hours = (
                (record.received_at - record.sent_at).total_seconds() / 3600
                if record.received_at and record.sent_at
                else 0
            )

    def action_send(self):
        require_role(self.env, "operator", "supervisor", "manager")
        for record in self:
            if record.quantity > record.production_id.product_qty or (
                record.batch_id and record.batch_id.production_id != record.production_id
            ):
                raise UserError("Handover quantity/batch must match this MO.")
            if record.receiver_id == self.env.user:
                raise UserError("Assign a separate receiver for acknowledgement.")
            internal(record).write({"sender_id": self.env.uid, "sent_at": fields.Datetime.now()})
        return self._transition(["draft"], "sent")

    def _receiver(self):
        require_role(self.env, "operator", "supervisor", "manager")
        if (
            not self.env.su
            and not self.env.user.has_group("deep_core.group_manager")
            and any(record.receiver_id != self.env.user for record in self)
        ):
            raise UserError("Only the designated receiver may acknowledge this handover.")

    def action_receive(self):
        self._receiver()
        for record in self:
            internal(record).write({"received_at": fields.Datetime.now()})
            if record.batch_id and not record.batch_id.material_arrival:
                record.batch_id.material_arrival = fields.Datetime.now()
        return self._transition(["sent"], "received")

    def action_reject(self):
        self._receiver()
        if any(not record.notes for record in self):
            raise UserError("Explain the rejected handover.")
        return self._transition(["sent"], "rejected")
