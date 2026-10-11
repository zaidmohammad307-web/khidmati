from odoo import fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_role


class Alternative(models.Model):
    _name = "deep.material.alternative"
    _description = "Approved Alternative Material / Advisory Only"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    alternative_id = fields.Many2one("product.product", required=True, check_company=True)
    quantity_factor = fields.Float(default=1, required=True)
    qualification = fields.Text(required=True)
    attachment_ids = fields.Many2many("ir.attachment")
    approved_by = fields.Many2one("res.users", readonly=True)
    valid_until = fields.Date()
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "approved", "obsolete"]], default="draft"
    )
    _factor = models.Constraint(
        "CHECK(quantity_factor>0 AND product_id!=alternative_id)",
        "Choose a different material and positive replacement factor.",
    )
    _unique = models.Constraint(
        "UNIQUE(company_id,product_id,alternative_id)", "Alternative mapping already exists."
    )
    _protected_fields = {"state", "approved_by"}

    def write(self, values):
        if any(record.state in ("approved", "obsolete") for record in self) and set(values) - {
            "state"
        }:
            raise AccessError("Approved alternatives are immutable; use a new engineering change.")
        return super().write(values)

    def action_approve(self):
        require_role(self.env, "manager")
        for record in self:
            if record.valid_until and record.valid_until < fields.Date.context_today(record):
                raise UserError("Alternative qualification has expired.")
            internal(record).write({"approved_by": self.env.uid})
        return self._transition(
            ["draft"],
            "approved",
            "Qualified alternative is advisory; actual BOM changes require engineering approval",
        )

    def action_obsolete(self):
        require_role(self.env, "manager")
        return self._transition(["approved"], "obsolete")
