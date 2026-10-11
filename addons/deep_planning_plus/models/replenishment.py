from datetime import timedelta
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import require_role, lock
from odoo.addons.deep_core.services.export import export_xlsx
from ..services.statistics import reorder_policy


class Policy(models.Model):
    _name = "deep.stock.policy"
    _description = "Consumption-based Reorder / Safety Stock Proposal"
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    warehouse_id = fields.Many2one("stock.warehouse", required=True, check_company=True)
    criticality = fields.Selection(
        [("A", "Critical"), ("B", "Important"), ("C", "Standard")], default="B", required=True
    )
    z_score = fields.Float(
        default=1.65,
        required=True,
        help="Configured service buffer; A/B/C classification remains a planner decision.",
    )
    history_days = fields.Integer(default=90, required=True)
    lead_days = fields.Float(default=14, required=True)
    coverage_days = fields.Float(default=30, required=True)
    daily_mean = fields.Float(readonly=True)
    daily_std = fields.Float(readonly=True)
    safety_qty = fields.Float(readonly=True)
    reorder_qty = fields.Float(readonly=True)
    maximum_qty = fields.Float(readonly=True)
    calculated_at = fields.Datetime(readonly=True)
    orderpoint_id = fields.Many2one("stock.warehouse.orderpoint", readonly=True, check_company=True)
    _valid = models.Constraint(
        "CHECK(history_days>0 AND history_days<=730 AND lead_days>=0 AND coverage_days>0 AND z_score>=0)",
        "Invalid replenishment settings.",
    )
    _unique = models.Constraint(
        "UNIQUE(company_id,product_id,warehouse_id)", "One policy per product/warehouse."
    )

    @api.model_create_multi
    def create(self, values):
        from odoo.addons.deep_core.security import require_internal

        computed = {
            "daily_mean",
            "daily_std",
            "safety_qty",
            "reorder_qty",
            "maximum_qty",
            "calculated_at",
            "orderpoint_id",
        }
        if any(any(value.get(key) for key in computed) for value in values):
            require_internal(self.env)
        return super().create(values)

    def action_calculate(self):
        require_role(self.env, "planner", "procurement", "manager")
        for policy in self:
            lock(policy)
            today = fields.Date.context_today(policy)
            first = today - timedelta(days=policy.history_days)
            daily = {first + timedelta(days=index): 0.0 for index in range(policy.history_days)}
            moves = self.env["stock.move"].search(
                [
                    ("company_id", "=", policy.company_id.id),
                    ("product_id", "=", policy.product_id.id),
                    ("state", "=", "done"),
                    ("location_id", "child_of", policy.warehouse_id.view_location_id.id),
                    ("location_dest_id.usage", "=", "production"),
                    ("date", ">=", str(first)),
                    ("date", "<", str(today)),
                ]
            )
            for move in moves:
                day = move.date.date()
                if day in daily:
                    daily[day] += move.product_uom._compute_quantity(
                        move.quantity, policy.product_id.uom_id
                    )
            values = reorder_policy(
                list(daily.values()),
                policy.lead_days,
                policy.coverage_days,
                policy.z_score,
                policy.product_id.uom_id.rounding,
            )
            from odoo.addons.deep_core.security import internal

            internal(policy).write({**values, "calculated_at": fields.Datetime.now()})
            self.env["deep.audit.event"]._record(
                policy,
                "stock_policy_calculated",
                reason="Actual native production consumption; zero-consumption days included",
            )
        return True

    def write(self, values):
        from odoo.addons.deep_core.security import require_internal

        if set(values) & {
            "daily_mean",
            "daily_std",
            "safety_qty",
            "reorder_qty",
            "maximum_qty",
            "calculated_at",
            "orderpoint_id",
        }:
            require_internal(self.env)
        result = super().write(values)
        if set(values) & {
            "product_id",
            "warehouse_id",
            "company_id",
            "z_score",
            "history_days",
            "lead_days",
            "coverage_days",
        }:
            from odoo.addons.deep_core.security import internal

            internal(self).write({"calculated_at": False})
        return result

    def action_apply_orderpoint(self):
        require_role(self.env, "manager")
        from odoo.addons.deep_core.security import internal

        for policy in self:
            lock(policy)
            if policy.company_id.deep_procurement_mode != "odoo":
                raise UserError(
                    "SAP procurement mode exports suggestions; native reorder rules require explicit Odoo procurement mode."
                )
            if not policy.calculated_at:
                raise UserError("Calculate the policy first.")
            orderpoint = policy.orderpoint_id or self.env["stock.warehouse.orderpoint"].search(
                [
                    ("product_id", "=", policy.product_id.id),
                    ("location_id", "=", policy.warehouse_id.lot_stock_id.id),
                    ("company_id", "=", policy.company_id.id),
                ],
                limit=1,
            )
            values = {
                "product_id": policy.product_id.id,
                "location_id": policy.warehouse_id.lot_stock_id.id,
                "company_id": policy.company_id.id,
                "product_min_qty": policy.reorder_qty,
                "product_max_qty": policy.maximum_qty,
                "trigger": "manual",
            }
            if orderpoint:
                orderpoint.write(values)
            else:
                orderpoint = self.env["stock.warehouse.orderpoint"].create(values)
            internal(policy).write({"orderpoint_id": orderpoint.id})
            self.env["deep.audit.event"]._record(
                policy, "manual_reorder_rule_applied", reason=orderpoint.display_name
            )
        return True

    def action_export(self):
        return export_xlsx(
            self,
            "Reorder_Proposals.xlsx",
            [
                "Item",
                "Warehouse",
                "Criticality",
                "Daily Mean",
                "Daily Std",
                "Lead Days",
                "Safety",
                "Reorder",
                "Maximum",
            ],
            [
                [
                    policy.product_id.default_code,
                    policy.warehouse_id.name,
                    policy.criticality,
                    policy.daily_mean,
                    policy.daily_std,
                    policy.lead_days,
                    policy.safety_qty,
                    policy.reorder_qty,
                    policy.maximum_qty,
                ]
                for policy in self
            ],
        )
