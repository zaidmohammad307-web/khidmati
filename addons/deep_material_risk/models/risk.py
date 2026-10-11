from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, require_role
from odoo.addons.deep_core.services.export import export_xlsx


class Product(models.Model):
    _inherit = "product.template"
    deep_sourcing = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")], default="low"
    )
    deep_restricted = fields.Boolean("Restricted / Special Source")
    deep_maturity = fields.Selection(
        [("mature", "Mature"), ("prototype", "Developing"), ("obsolete", "Obsolescence Risk")],
        default="mature",
    )


class Risk(models.Model):
    _name = "deep.material.risk"
    _inherit = "deep.service.result"
    _description = "Material Criticality Snapshot"
    company_id = fields.Many2one("res.company", required=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    supplier_count = fields.Integer()
    lead_days = fields.Float()
    final_bom_count = fields.Integer()
    total_bom_usage = fields.Float()
    average_price = fields.Float()
    last_price = fields.Float()
    score = fields.Float()
    reasons = fields.Text()
    at = fields.Datetime(default=fields.Datetime.now)

    @api.model
    def action_refresh(self):
        require_role(self.env, "planner", "procurement", "manager")
        c = self.env.company
        internal(self.search([("company_id", "=", c.id)])).unlink()
        boms = self.env["mrp.bom"].search([("company_id", "=", c.id), ("active", "=", True)])
        mapping = {
            p.id: b for b in boms for p in b.product_id or b.product_tmpl_id.product_variant_ids
        }
        usage = {}

        def explode(p, multiplier, final_id, path):
            if p.id in path:
                return
            bom = mapping.get(p.id)
            if not bom:
                entry = usage.setdefault(p.id, {"boms": set(), "quantity": 0})
                entry["boms"].add(final_id)
                entry["quantity"] += multiplier
                return
            for planning_line in bom.bom_line_ids:
                qty = (
                    planning_line.product_uom_id._compute_quantity(
                        planning_line.product_qty, planning_line.product_id.uom_id
                    )
                    / bom.product_qty
                )
                explode(planning_line.product_id, multiplier * qty, final_id, path | {p.id})

        for b in boms.filtered(lambda b: b.product_tmpl_id.deep_qa_required):
            for p in b.product_id or b.product_tmpl_id.product_variant_ids:
                explode(p, 1, b.id, set())
        products = self.env["product.product"].search(
            [
                ("deep_make_buy", "=", "buy"),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", c.id),
            ]
        )
        purchases = self.env["purchase.order.line"].search(
            [
                ("company_id", "=", c.id),
                ("product_id", "in", products.ids),
                ("order_id.state", "in", ["purchase", "done"]),
            ],
            order="date_order desc,id desc",
        )
        rows = []
        for p in products:
            sellers = p.seller_ids.filtered(lambda s: not s.company_id or s.company_id == c)
            count = len(sellers.partner_id)
            lead = max(sellers.mapped("delay"), default=0)
            lines = purchases.filtered(lambda planning_line: planning_line.product_id == p)
            prices = [
                planning_line.currency_id._convert(
                    planning_line.price_unit, c.currency_id, c, planning_line.date_order.date()
                )
                for planning_line in lines
            ]
            used = usage.get(p.id, {"boms": set(), "quantity": 0})
            reasons = []
            if count < 2:
                reasons.append("No alternate supplier")
            if lead > 30:
                reasons.append("Lead time >30 days")
            if p.deep_restricted:
                reasons.append("Restricted source")
            if p.deep_maturity != "mature":
                reasons.append(p.deep_maturity)
            score = min(
                100,
                {"low": 0, "medium": 15, "high": 30}[p.deep_sourcing or "low"]
                + (30 if count == 0 else 15 if count == 1 else 0)
                + min(20, lead / 3)
                + (15 if p.deep_restricted else 0)
                + ({"mature": 0, "prototype": 5, "obsolete": 15}[p.deep_maturity or "mature"])
                + min(10, len(used["boms"]) * 2),
            )
            rows.append(
                {
                    "company_id": c.id,
                    "product_id": p.id,
                    "supplier_count": count,
                    "lead_days": lead,
                    "final_bom_count": len(used["boms"]),
                    "total_bom_usage": used["quantity"],
                    "average_price": sum(prices) / len(prices) if prices else 0,
                    "last_price": prices[0] if prices else 0,
                    "score": score,
                    "reasons": "\n".join(reasons),
                }
            )
        internal(self).create(rows)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "list,form,graph,pivot",
        }

    def action_export(self):
        return export_xlsx(
            self,
            "Material_Risk.xlsx",
            [
                "Item",
                "Suppliers",
                "Lead Days",
                "Final BOMs",
                "Usage per Final BOMs",
                "Average Price",
                "Last Price",
                "Score",
                "Reasons",
            ],
            [
                [
                    r.product_id.default_code,
                    r.supplier_count,
                    r.lead_days,
                    r.final_bom_count,
                    r.total_bom_usage,
                    r.average_price,
                    r.last_price,
                    r.score,
                    r.reasons or "",
                ]
                for r in self
            ],
        )
