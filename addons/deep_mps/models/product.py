from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"
    deep_safety_stock = fields.Float(
        "Safety Stock",
        help="Buffer kept for this item in its stock unit. Zero uses the plan default.",
    )
    deep_lot_minimum = fields.Float(
        "Minimum Lot", help="Smallest quantity planned per make or buy order (MOQ)."
    )
    deep_lot_multiple = fields.Float(
        "Lot Multiple", help="Planned quantities are rounded up to this batch or pack size."
    )
    _deep_planning_policy = models.Constraint(
        "CHECK(deep_safety_stock>=0 AND deep_lot_minimum>=0 AND deep_lot_multiple>=0)",
        "Safety stock and lot sizes cannot be negative.",
    )
