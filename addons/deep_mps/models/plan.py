from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import require_role, require_internal, internal, lock
from odoo.addons.deep_core.services.export import export_xlsx
from ..services.planning import MPSService
from ..services.materials import MaterialService


class Plan(models.Model):
    _name = "deep.mps.plan"
    _description = "Master Production Schedule"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    name = fields.Char(required=True, default="Production Plan")
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        required=True,
        check_company=True,
        default=lambda s: s.env["stock.warehouse"].search(
            [("company_id", "=", s.env.company.id)], limit=1
        ),
    )
    product_ids = fields.Many2many("product.product", check_company=True)
    start_date = fields.Date(required=True, default=fields.Date.context_today)
    horizon = fields.Selection(
        [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
        default="weekly",
        required=True,
    )
    bucket_count = fields.Integer(default=12, required=True)
    strategy = fields.Selection(
        [("consume", "Firm Consumes Forecast"), ("add", "Firm + Incremental Forecast")],
        default="consume",
        required=True,
    )
    safety_stock = fields.Float()
    state = fields.Selection(
        [(s, s.title()) for s in ["draft", "reviewed", "approved", "firm", "released"]],
        default="draft",
        readonly=True,
        required=True,
        tracking=True,
    )
    period_ids = fields.One2many("deep.mps.period", "plan_id", copy=False, readonly=True)
    line_ids = fields.One2many("deep.mps.line", "plan_id", copy=False, readonly=True)
    requirement_ids = fields.One2many(
        "deep.material.requirement", "plan_id", copy=False, readonly=True
    )
    demand_ids = fields.One2many("deep.demand", "plan_id")
    source_demand_ids = fields.Many2many("deep.demand", readonly=True, copy=False)
    warnings = fields.Text(readonly=True)
    warnings_acknowledged = fields.Boolean()
    approval_reason = fields.Text()
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    calculated_at = fields.Datetime(readonly=True)
    frozen_until = fields.Date()
    _settings = models.Constraint(
        "CHECK(bucket_count>0 AND bucket_count<=366 AND safety_stock>=0)",
        "Invalid horizon or safety stock.",
    )

    def _deep_available_stock(self, product):
        self.ensure_one()
        return product.with_context(warehouse_id=self.warehouse_id.id).free_qty

    def _deep_native_supply(self, products, source_usages=None):
        self.ensure_one()
        moves = self.env["stock.move"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("product_id", "in", products.ids),
                ("state", "not in", ["draft", "done", "cancel"]),
                ("location_id.usage", "in", source_usages or ["supplier", "production"]),
                ("location_dest_id", "child_of", self.warehouse_id.view_location_id.id),
            ],
            order="date,id",
        )
        result = {product.id: [] for product in products}
        for move in moves:
            result[move.product_id.id].append(
                [
                    move.date.date(),
                    move.product_uom._compute_quantity(
                        move.product_uom_qty, move.product_id.uom_id
                    ),
                ]
            )
        return result

    def _deep_incoming_supply(self, products):
        return self._deep_native_supply(products)

    def _deep_demand_domain(self, end_date):
        self.ensure_one()
        return [
            ("company_id", "=", self.company_id.id),
            ("required_date", ">=", self.start_date),
            ("required_date", "<=", end_date),
            "|",
            ("plan_id", "=", self.id),
            ("plan_id", "=", False),
        ]

    @api.model_create_multi
    def create(self, vals):
        if any(v.get("state", "draft") != "draft" for v in vals):
            raise UserError("New plans start in Draft.")
        return super().create(vals)

    def write(self, vals):
        if set(vals) & {
            "state",
            "warnings",
            "calculated_at",
            "approved_by",
            "approved_at",
            "source_demand_ids",
        }:
            require_internal(self.env)
        if set(vals) & {
            "company_id",
            "warehouse_id",
            "start_date",
            "horizon",
            "bucket_count",
            "strategy",
            "product_ids",
            "safety_stock",
            "demand_ids",
        }:
            if any(p.state != "draft" for p in self):
                raise UserError("Reviewed plan inputs are frozen; create a revision.")
            result = super().write(vals)
            internal(self).write({"calculated_at": False, "warnings_acknowledged": False})
            return result
        return super().write(vals)

    def unlink(self):
        if any(p.state != "draft" for p in self):
            raise UserError("Reviewed planning history cannot be deleted.")
        return super().unlink()

    def action_calculate(self):
        require_role(self.env, "planner", "manager")
        for p in self:
            lock(p)
            if p.state not in ("draft", "reviewed"):
                raise UserError("Only a draft/reviewed plan can be calculated.")
            if p.frozen_until and p.start_date <= p.frozen_until:
                raise UserError("The plan overlaps its frozen horizon.")
            MPSService(self.env).calculate(p)
            MaterialService(self.env).calculate(p)
        return True

    def _advance(self, allowed, target):
        require_role(self.env, "planner", "manager")
        for p in self:
            lock(p)
            if p.state not in allowed:
                raise UserError("The plan is not eligible for this transition.")
            before = p.state
            internal(p).write({"state": target})
            self.env["deep.audit.event"]._record(
                p, "mps_" + target, before, target, p.approval_reason or ""
            )
        return True

    def action_review(self):
        if any(not p.calculated_at or not p.line_ids for p in self):
            raise UserError("Calculate the plan first.")
        return self._advance(["draft"], "reviewed")

    def action_approve(self):
        for p in self:
            if p.warnings and (not p.warnings_acknowledged or not p.approval_reason):
                raise UserError("Acknowledge the warnings and record an approval reason.")
        self._advance(["reviewed"], "approved")
        internal(self).write({"approved_by": self.env.uid, "approved_at": fields.Datetime.now()})
        return True

    def action_firm(self):
        return self._advance(["approved"], "firm")

    def action_release(self):
        require_role(self.env, "planner", "manager")
        for p in self:
            lock(p)
            if p.state == "released":
                continue
            if p.state not in ("approved", "firm"):
                raise UserError("Approve the plan before creating operational orders.")
            MaterialService(self.env).release(p)
            p._advance(["approved", "firm"], "released")
        return True

    def action_requirements(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.material.requirement",
            "view_mode": "list,form,pivot,graph",
            "domain": [("plan_id", "=", self.id)],
        }

    def action_export(self):
        self.ensure_one()
        return export_xlsx(
            self,
            "MPS.xlsx",
            [
                "Item",
                "Period",
                "Firm",
                "Forecast",
                "Weighted Demand",
                "Beginning",
                "Receipts",
                "Planned",
                "Actual",
                "Balance",
                "Variance",
            ],
            [
                [
                    planning_line.product_id.default_code,
                    planning_line.period_id.name,
                    planning_line.firm,
                    planning_line.forecast,
                    planning_line.weighted_demand,
                    planning_line.beginning,
                    planning_line.receipts,
                    planning_line.planned,
                    planning_line.actual,
                    planning_line.balance,
                    planning_line.variance,
                ]
                for planning_line in self.line_ids
            ],
        )
