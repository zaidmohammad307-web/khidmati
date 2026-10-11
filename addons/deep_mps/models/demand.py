from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import require_internal, internal


class Demand(models.Model):
    _name = "deep.demand"
    _description = "Contract / Project / Forecast Demand"
    _inherit = "mail.thread"
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    plan_id = fields.Many2one("deep.mps.plan", check_company=True, index=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True, index=True)
    category = fields.Selection(
        [
            ("firm", "Confirmed Contract"),
            ("project", "Project Milestone"),
            ("forecast", "Forecast"),
            ("manual", "Incremental Manual"),
        ],
        default="firm",
        required=True,
    )
    required_date = fields.Date(required=True, index=True)
    quantity = fields.Float(required=True)
    confidence = fields.Float(default=100)
    contract = fields.Char()
    milestone = fields.Char()
    external_id = fields.Char(index=True)
    released_plan_id = fields.Many2one("deep.mps.plan", readonly=True, check_company=True)
    _positive = models.Constraint(
        "CHECK(quantity>0 AND confidence>=0 AND confidence<=100)",
        "Invalid demand quantity/confidence.",
    )
    _source = models.Constraint("UNIQUE(company_id,external_id)", "Demand source already exists.")

    def _is_frozen(self):
        return bool(
            any(d.released_plan_id or (d.plan_id and d.plan_id.state != "draft") for d in self)
            or self.env["deep.mps.plan"]
            .sudo()
            .search_count(
                [
                    ("source_demand_ids", "in", self.ids),
                    ("state", "in", ["reviewed", "approved", "firm", "released"]),
                ],
                limit=1,
            )
        )

    def _invalidate_draft_plans(self):
        plans = (
            self.env["deep.mps.plan"]
            .sudo()
            .search(
                [
                    ("company_id", "in", self.company_id.ids),
                    ("state", "=", "draft"),
                ]
            )
        )
        internal(plans).write({"calculated_at": False, "warnings_acknowledged": False})

    @api.model_create_multi
    def create(self, vals):
        if any(v.get("released_plan_id") for v in vals):
            require_internal(self.env)
        plans = self.env["deep.mps.plan"].browse([v["plan_id"] for v in vals if v.get("plan_id")])
        if any(p.state != "draft" for p in plans):
            raise UserError("Approved demand is frozen; create a revision.")
        records = super().create(vals)
        records._invalidate_draft_plans()
        return records

    def write(self, vals):
        if "released_plan_id" in vals:
            require_internal(self.env)
        elif self._is_frozen():
            raise UserError("Approved demand is frozen; create a revision.")
        result = super().write(vals)
        if "released_plan_id" not in vals:
            self._invalidate_draft_plans()
        return result

    def unlink(self):
        if self._is_frozen():
            raise UserError("Approved demand cannot be deleted.")
        self._invalidate_draft_plans()
        return super().unlink()
