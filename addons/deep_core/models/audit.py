from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..security import internal, require_internal


class Audit(models.Model):
    _name = "deep.audit.event"
    _description = "Immutable Manufacturing Audit"
    _order = "at desc, id desc"
    company_id = fields.Many2one("res.company", required=True, index=True)
    user_id = fields.Many2one("res.users", required=True)
    at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    model = fields.Char(required=True)
    res_id = fields.Integer(required=True, index=True)
    action = fields.Char(required=True, index=True)
    before = fields.Char()
    after = fields.Char()
    reason = fields.Text()
    unit_id = fields.Many2one("deep.production.unit", ondelete="restrict", index=True)

    @api.model
    def _record(self, record, action, before="", after="", reason="", unit=False):
        record.ensure_one()
        return internal(self.sudo()).create(
            {
                "company_id": record.company_id.id,
                "user_id": self.env.uid,
                "model": record._name,
                "res_id": record.id,
                "action": action,
                "before": str(before),
                "after": str(after),
                "reason": reason,
                "unit_id": unit.id if unit else False,
            }
        )

    @api.model_create_multi
    def create(self, vals):
        require_internal(self.env)
        return super().create(vals)

    def write(self, vals):
        raise AccessError("Audit history is immutable.")

    def unlink(self):
        raise AccessError("Audit history is permanent.")


class Batch(models.Model):
    _name = "deep.production.batch"
    _description = "Production Batch Shift Traceability"
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    production_id = fields.Many2one("mrp.production", required=True, check_company=True, index=True)
    lot_id = fields.Many2one("stock.lot", check_company=True)
    shift_name = fields.Char(required=True)
    start = fields.Datetime(required=True)
    end = fields.Datetime(required=True)
    employee_ids = fields.Many2many("hr.employee", check_company=True)
    material_arrival = fields.Datetime()
    completed_at = fields.Datetime()
    flow_hours = fields.Float(compute="_compute_flow")
    _interval = models.Constraint('CHECK("end" > start)', "Shift end must follow its start.")

    @api.depends("material_arrival", "completed_at")
    def _compute_flow(self):
        for r in self:
            r.flow_hours = (
                (r.completed_at - r.material_arrival).total_seconds() / 3600
                if r.completed_at and r.material_arrival
                else 0
            )
