from odoo import fields, models
from ..services.math import operation_minutes


class Center(models.Model):
    _inherit = "mrp.workcenter"
    deep_required_operators = fields.Integer(default=1)
    deep_category = fields.Char()
    deep_notes = fields.Text()


class Workorder(models.Model):
    _inherit = "mrp.workorder"

    def _get_duration_expected(self, alternative_workcenter=False, ratio=1):
        self.ensure_one()
        op = self.operation_id
        if not op or (op.deep_setup < 0 and op.deep_cleanup < 0 and not op.deep_batch_size):
            return super()._get_duration_expected(alternative_workcenter, ratio)
        center = alternative_workcenter or self.workcenter_id
        capacity, setup, cleanup = center._get_capacity(
            self.product_id,
            self.production_id.product_uom_id,
            self.production_id.bom_id.product_qty,
        )
        return operation_minutes(
            max(0, self.qty_production - self.qty_produced) * ratio,
            op.time_cycle,
            capacity,
            center.time_efficiency,
            op.deep_setup if op.deep_setup >= 0 else setup,
            op.deep_cleanup if op.deep_cleanup >= 0 else cleanup,
            op.deep_batch_size,
        )
