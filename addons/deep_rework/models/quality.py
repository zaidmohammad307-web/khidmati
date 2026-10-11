from odoo import fields, models
from odoo.addons.deep_core.security import internal
from odoo.exceptions import UserError


class Session(models.Model):
    _inherit = "deep.quality.session"

    def _on_started(self):
        super()._on_started()
        orders = (
            self.env["deep.rework.order"]
            .sudo()
            .search([("unit_id", "in", self.unit_id.ids), ("state", "=", "ready")])
        )
        internal(orders).write({"state": "retesting"})
        return True

    def _on_failure(self):
        super()._on_failure()
        for s in self:
            prior = (
                self.env["deep.rework.order"]
                .sudo()
                .search([("unit_id", "=", s.unit_id.id), ("state", "=", "retesting")])
            )
            internal(prior).write(
                {"state": "closed", "completed_at": fields.Datetime.now(), "retest_id": s.id}
            )
            failed = s.result_ids.filtered(lambda r: not r.passed)
            order = internal(self.env["deep.rework.order"].sudo()).create(
                {
                    "company_id": s.company_id.id,
                    "unit_id": s.unit_id.id,
                    "session_id": s.id,
                    "description": "\n".join(
                        r.point_id.name + ": " + (r.failure_code or "FAIL") for r in failed
                    )
                    or s.notes,
                }
            )
            self.env["deep.audit.event"]._record(order, "rework_created", unit=s.unit_id)
        return True

    def _on_pass(self):
        super()._on_pass()
        for s in self:
            orders = (
                self.env["deep.rework.order"]
                .sudo()
                .search([("unit_id", "=", s.unit_id.id), ("state", "=", "retesting")])
            )
            internal(orders).write(
                {"state": "closed", "completed_at": fields.Datetime.now(), "retest_id": s.id}
            )
            for r in orders:
                self.env["deep.audit.event"]._record(r, "retest_passed", unit=s.unit_id)
        return True


class Unit(models.Model):
    _inherit = "deep.production.unit"
    rework_ids = fields.One2many("deep.rework.order", "unit_id", readonly=True)

    def _check_release(self):
        super()._check_release()
        if any(r.state not in ("closed", "scrapped") for r in self.rework_ids):
            raise UserError("Open product rework blocks final release.")
