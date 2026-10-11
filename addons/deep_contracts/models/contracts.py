from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_internal, require_role, lock
from odoo.addons.deep_core.services.export import export_xlsx


class Contract(models.Model):
    _name = "deep.customer.contract"
    _description = "Customer Contract / Project Delivery Milestones"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    reference = fields.Char(required=True)
    customer_id = fields.Many2one("res.partner", required=True, check_company=True)
    owner_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    priority = fields.Selection(
        [("normal", "Normal"), ("high", "High"), ("critical", "Critical")], default="normal"
    )
    notes = fields.Text()
    line_ids = fields.One2many("deep.contract.milestone", "contract_id", copy=True)
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "confirmed", "closed"]], default="draft"
    )
    _reference = models.Constraint(
        "UNIQUE(company_id,reference)", "Contract reference already exists."
    )

    def write(self, values):
        if any(contract.state != "draft" for contract in self) and set(values) & {
            "company_id",
            "reference",
            "customer_id",
            "line_ids",
        }:
            raise AccessError("Confirmed contract inputs are frozen; create an amendment.")
        return super().write(values)

    def action_confirm(self):
        require_role(self.env, "planner", "manager")
        for contract in self:
            lock(contract)
            if contract.state == "confirmed":
                continue
            if contract.state != "draft" or not contract.line_ids:
                raise UserError("Confirm a draft contract with delivery milestones.")
            for line in contract.line_ids:
                demand = self.env["deep.demand"].create(
                    {
                        "name": contract.reference + " / " + line.name,
                        "company_id": contract.company_id.id,
                        "product_id": line.product_id.id,
                        "category": "project",
                        "quantity": line.quantity,
                        "required_date": line.due_date,
                        "confidence": 100,
                        "contract": contract.reference,
                        "milestone": line.name,
                        "external_id": "CONTRACT:" + str(contract.id) + ":" + str(line.id),
                        "deep_contract_line_id": line.id,
                    }
                )
                internal(line).write({"demand_id": demand.id})
            contract._transition(
                ["draft"], "confirmed", "Firm milestone demand registered once in MPS"
            )
        return True

    def action_close(self):
        require_role(self.env, "planner", "manager")
        if any(
            any(line.delivered_qty < line.quantity for line in contract.line_ids)
            for contract in self
        ):
            raise UserError("Complete every native customer delivery before closing the contract.")
        return self._transition(["confirmed"], "closed")

    def action_export(self):
        return export_xlsx(
            self,
            "Contract_Delivery_Status.xlsx",
            [
                "Contract",
                "Customer",
                "Milestone",
                "Item",
                "Required",
                "Delivered",
                "Remaining",
                "Due",
                "Status",
            ],
            [
                [
                    contract.reference,
                    contract.customer_id.name,
                    line.name,
                    line.product_id.default_code,
                    line.quantity,
                    line.delivered_qty,
                    line.remaining_qty,
                    str(line.due_date),
                    line.delivery_status,
                ]
                for contract in self
                for line in contract.line_ids
            ],
        )


class Milestone(models.Model):
    _name = "deep.contract.milestone"
    _description = "Contract Delivery Milestone"
    _check_company_auto = True
    name = fields.Char(required=True)
    contract_id = fields.Many2one("deep.customer.contract", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="contract_id.company_id", store=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    quantity = fields.Float(required=True)
    due_date = fields.Date(required=True, index=True)
    demand_id = fields.Many2one("deep.demand", readonly=True, check_company=True, copy=False)
    picking_ids = fields.One2many("stock.picking", "deep_contract_line_id", readonly=True)
    delivered_qty = fields.Float(compute="_delivery")
    remaining_qty = fields.Float(compute="_delivery")
    delivery_status = fields.Selection(
        [(key, key.title()) for key in ["open", "late", "partial", "complete"]], compute="_delivery"
    )
    _positive = models.Constraint("CHECK(quantity>0)", "Milestone quantity must be positive.")

    def write(self, values):
        if set(values) & {"demand_id"}:
            require_internal(self.env)
        if set(values) - {"demand_id"} and any(line.contract_id.state != "draft" for line in self):
            raise AccessError("Confirmed milestones are frozen.")
        return super().write(values)

    @api.model_create_multi
    def create(self, values):
        contracts = self.env["deep.customer.contract"].browse(
            [value["contract_id"] for value in values]
        )
        if any(contract.state != "draft" for contract in contracts):
            raise AccessError("Confirmed milestones are frozen.")
        if any(value.get("demand_id") for value in values):
            require_internal(self.env)
        return super().create(values)

    def unlink(self):
        if any(line.contract_id.state != "draft" for line in self):
            raise AccessError("Confirmed milestones are permanent.")
        return super().unlink()

    @api.depends(
        "picking_ids.move_ids.state", "picking_ids.move_ids.quantity", "quantity", "due_date"
    )
    def _delivery(self):
        for line in self:
            moves = line.picking_ids.move_ids.filtered(
                lambda move: move.state == "done" and move.product_id == line.product_id
            )
            delivered = sum(
                move.product_uom._compute_quantity(move.quantity, line.product_id.uom_id)
                * (
                    -1
                    if move.location_id.usage == "customer"
                    else 1
                    if move.location_dest_id.usage == "customer"
                    else 0
                )
                for move in moves
            )
            line.delivered_qty = max(0, delivered)
            line.remaining_qty = max(0, line.quantity - line.delivered_qty)
            line.delivery_status = (
                "complete"
                if not line.remaining_qty
                else "late"
                if line.due_date < fields.Date.context_today(line)
                else "partial"
                if delivered
                else "open"
            )

    def action_prepare_delivery(self):
        require_role(self.env, "warehouse", "manager")
        self.ensure_one()
        lock(self)
        if self.contract_id.state != "confirmed" or self.remaining_qty <= 0:
            raise UserError("Prepare a remaining confirmed contract milestone.")
        pending = self.picking_ids.filtered(lambda picking: picking.state not in ("done", "cancel"))
        if pending:
            picking = pending[0]
        else:
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", self.company_id.id)], limit=1
            )
            source = warehouse.lot_stock_id
            target = self.contract_id.customer_id.with_company(
                self.company_id
            ).property_stock_customer
            picking = self.env["stock.picking"].create(
                {
                    "partner_id": self.contract_id.customer_id.id,
                    "company_id": self.company_id.id,
                    "picking_type_id": warehouse.out_type_id.id,
                    "location_id": source.id,
                    "location_dest_id": target.id,
                    "scheduled_date": str(self.due_date) + " 12:00:00",
                    "origin": self.contract_id.reference + " / " + self.name,
                    "deep_contract_line_id": self.id,
                }
            )
            self.env["stock.move"].create(
                {
                    "description_picking_manual": self.product_id.display_name,
                    "product_id": self.product_id.id,
                    "product_uom": self.product_id.uom_id.id,
                    "product_uom_qty": self.remaining_qty,
                    "location_id": source.id,
                    "location_dest_id": target.id,
                    "company_id": self.company_id.id,
                    "picking_id": picking.id,
                }
            )
            picking.action_confirm()
            picking.action_assign()
            self.env["deep.audit.event"]._record(
                self, "contract_delivery_prepared", reason=picking.name
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": picking.id,
            "view_mode": "form",
        }
