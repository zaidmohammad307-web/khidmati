from odoo import Command, api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_role
from odoo.addons.deep_core.services.export import export_xlsx
from odoo.exceptions import UserError


class Period(models.Model):
    _name = "deep.mps.period"
    _inherit = "deep.service.result"
    _description = "Planning Bucket"
    _order = "start_date"
    name = fields.Char(required=True)
    plan_id = fields.Many2one("deep.mps.plan", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="plan_id.company_id", store=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    _interval = models.Constraint("CHECK(end_date>=start_date)", "Invalid period interval.")


class Line(models.Model):
    _name = "deep.mps.line"
    _inherit = "deep.service.result"
    _description = "MPS Product / Period Balance"
    _check_company_auto = True
    _order = "period_id,product_id"
    plan_id = fields.Many2one("deep.mps.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True)
    period_id = fields.Many2one("deep.mps.period", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, check_company=True, index=True)
    firm = fields.Float()
    forecast = fields.Float()
    manual = fields.Float()
    confidence = fields.Float()
    weighted_demand = fields.Float()
    total_demand = fields.Float()
    beginning = fields.Float()
    receipts = fields.Float()
    planned = fields.Float()
    balance = fields.Float()
    actual = fields.Float(compute="_compute_actual")
    variance = fields.Float(compute="_compute_actual")
    production_ids = fields.One2many("mrp.production", "deep_mps_line_id")
    _unique = models.Constraint(
        "UNIQUE(plan_id,period_id,product_id)", "Duplicate planning bucket."
    )

    @api.depends("production_ids.state", "production_ids.qty_produced", "planned")
    def _compute_actual(self):
        for planning_line in self:
            planning_line.actual = sum(
                p.qty_produced
                for p in planning_line.production_ids
                if p.state == "done" and p.product_id == planning_line.product_id
            )
            planning_line.variance = planning_line.actual - planning_line.planned

    @api.constrains("period_id", "plan_id")
    def _period(self):
        if any(planning_line.period_id.plan_id != planning_line.plan_id for planning_line in self):
            raise UserError("Period and plan mismatch.")


class Requirement(models.Model):
    _name = "deep.material.requirement"
    _inherit = "deep.service.result"
    _description = "Date Specific Make / Buy Requirement"
    _check_company_auto = True
    _order = "required_date,product_id"
    plan_id = fields.Many2one("deep.mps.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True)
    line_id = fields.Many2one("deep.mps.line", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    bom_id = fields.Many2one("mrp.bom", check_company=True)
    kind = fields.Selection([("make", "MAKE"), ("buy", "BUY")], required=True)
    path = fields.Char()
    required_date = fields.Date(required=True, index=True)
    gross = fields.Float()
    stock_allocated = fields.Float()
    receipt_allocated = fields.Float()
    net = fields.Float()
    supplier_id = fields.Many2one("res.partner", check_company=True)
    lead_days = fields.Float()
    expected_date = fields.Date()
    shortage = fields.Boolean(index=True)
    warning = fields.Char()
    production_id = fields.Many2one("mrp.production", readonly=True, check_company=True)
    purchase_id = fields.Many2one("purchase.order", readonly=True, check_company=True)

    def action_export(self):
        return export_xlsx(
            self,
            "Material_Requirements.xlsx",
            [
                "Item",
                "Type",
                "Date",
                "Path",
                "Gross",
                "Stock",
                "Receipts",
                "Net",
                "Supplier",
                "Lead Days",
                "Expected Date",
                "Warning",
            ],
            [
                [
                    r.product_id.default_code,
                    r.kind,
                    str(r.required_date),
                    r.path,
                    r.gross,
                    r.stock_allocated,
                    r.receipt_allocated,
                    r.net,
                    r.supplier_id.display_name,
                    str(r.lead_days),
                    str(r.expected_date),
                    r.warning or "",
                ]
                for r in self
            ],
        )

    def action_create_rfq(self):
        require_role(self.env, "procurement", "manager")
        for r in self:
            lock(r)
            if r.company_id.deep_procurement_mode != "odoo":
                raise UserError(
                    "Procurement remains in SAP B1. Export the approved BUY suggestions."
                )
            if r.plan_id.state not in ("approved", "firm", "released"):
                raise UserError("Approve the plan first.")
            if r.purchase_id:
                continue
            if r.kind != "buy" or r.net <= 0 or not r.supplier_id:
                raise UserError("A positive BUY requirement and supplier are needed.")
            seller = r.product_id._select_seller(
                partner_id=r.supplier_id,
                quantity=r.net,
                date=r.required_date,
                uom_id=r.product_id.uom_id,
            )
            if not seller:
                raise UserError("No applicable vendor price exists.")
            currency = r.supplier_id.property_purchase_currency_id or r.company_id.currency_id
            price = seller.currency_id._convert(
                seller.price, currency, r.company_id, r.required_date
            )
            po = self.env["purchase.order"].create(
                {
                    "partner_id": r.supplier_id.id,
                    "company_id": r.company_id.id,
                    "currency_id": currency.id,
                    "origin": r.plan_id.name,
                    "order_line": [
                        Command.create(
                            {
                                "product_id": r.product_id.id,
                                "product_qty": r.net,
                                "product_uom_id": r.product_id.uom_id.id,
                                "name": r.product_id.display_name,
                                "price_unit": price,
                                "date_planned": str(r.required_date) + " 12:00:00",
                            }
                        )
                    ],
                }
            )
            internal(r).write({"purchase_id": po.id})
            self.env["deep.audit.event"]._record(
                po, "approved_requirement_rfq", reason=r.plan_id.name
            )
        return True


class Production(models.Model):
    _inherit = "mrp.production"
    deep_mps_line_id = fields.Many2one("deep.mps.line", check_company=True, index=True, copy=False)
    deep_requirement_id = fields.Many2one(
        "deep.material.requirement", check_company=True, index=True, copy=False
    )
    _requirement = models.Constraint(
        "UNIQUE(deep_requirement_id)", "This requirement already has a manufacturing order."
    )
