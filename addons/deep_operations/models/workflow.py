from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_internal, require_role, lock


class Workflow(models.AbstractModel):
    _name = "deep.workflow.document"
    _description = "Audited Manufacturing Workflow"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    state = fields.Selection(
        lambda _model: [("draft", "Draft"), ("done", "Done")],
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
    )
    _frozen_states = ("done", "closed", "cancel", "applied")
    _protected_fields = {"state"}

    @api.model_create_multi
    def create(self, values):
        default = self.default_get(["state"]).get("state")
        if any(
            value.get("state", default) != default
            or any(value.get(key) for key in self._protected_fields - {"state", "name"})
            for value in values
        ):
            require_internal(self.env)
        return super().create(values)

    def write(self, values):
        if set(values) & self._protected_fields:
            require_internal(self.env)
        if any(record.state in self._frozen_states for record in self):
            raise AccessError("Completed workflow history is locked.")
        return super().write(values)

    def unlink(self):
        require_role(self.env, "manager")
        if any(record.state != "draft" for record in self):
            raise AccessError("Submitted workflow history is permanent.")
        return super().unlink()

    def _transition(self, allowed, target, reason=""):
        for record in self:
            lock(record)
            if record.state not in allowed:
                raise UserError("This record is not eligible for the requested transition.")
            previous = record.state
            internal(record).write({"state": target})
            self.env["deep.audit.event"]._record(
                record, "workflow_" + target, previous, target, reason
            )
        return True
