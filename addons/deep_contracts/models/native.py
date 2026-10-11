from odoo import fields, models
from odoo.addons.deep_core.security import lock
from odoo.exceptions import AccessError, UserError


class Picking(models.Model):
    _inherit = "stock.picking"
    deep_contract_line_id = fields.Many2one(
        "deep.contract.milestone", check_company=True, copy=True, index=True
    )

    def button_validate(self):
        for picking in self.filtered(lambda record: record.deep_contract_line_id):
            line = picking.deep_contract_line_id
            if picking.partner_id != line.contract_id.customer_id:
                raise UserError("Delivery customer must match the contract.")
            if any(move.product_id != line.product_id for move in picking.move_ids):
                raise UserError("Deliver only the product assigned to this milestone.")
            outgoing = picking.move_ids.filtered(
                lambda move: (
                    move.location_dest_id.usage == "customer"
                    and move.state not in ("done", "cancel")
                )
            )
            actual = sum(
                move.product_uom._compute_quantity(move.quantity, line.product_id.uom_id)
                for move in outgoing
            )
            if actual > line.remaining_qty:
                raise UserError("Actual delivery exceeds the remaining milestone quantity.")
        return super().button_validate()


class Demand(models.Model):
    _inherit = "deep.demand"
    deep_contract_line_id = fields.Many2one(
        "deep.contract.milestone", check_company=True, copy=False
    )

    def write(self, values):
        if any(
            demand.deep_contract_line_id.contract_id.state != "draft"
            for demand in self.filtered("deep_contract_line_id")
        ) and set(values) & {
            "deep_contract_line_id",
            "name",
            "company_id",
            "product_id",
            "quantity",
            "required_date",
            "category",
            "confidence",
            "contract",
            "milestone",
            "external_id",
            "plan_id",
        }:
            raise AccessError("Confirmed contract demand is frozen; register an amendment.")
        return super().write(values)

    def unlink(self):
        if self.filtered(
            lambda demand: demand.deep_contract_line_id.contract_id.state in ("confirmed", "closed")
        ):
            raise AccessError("Confirmed contract demand is permanent.")
        return super().unlink()


class Move(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        moves = self.filtered(
            lambda move: (
                move.state not in ("done", "cancel")
                and move.location_dest_id.usage == "customer"
                and move.picking_id.deep_contract_line_id
            )
        )
        for line in moves.picking_id.deep_contract_line_id:
            lock(line)
            selected = moves.filtered(lambda move: move.picking_id.deep_contract_line_id == line)
            if line.contract_id.state != "confirmed" or any(
                move.product_id != line.product_id
                or move.picking_id.partner_id != line.contract_id.customer_id
                for move in selected
            ):
                raise UserError("Deliver the confirmed contract product to its assigned customer.")
            actual = sum(
                move.product_uom._compute_quantity(move.quantity, line.product_id.uom_id)
                for move in selected
            )
            if line.product_id.uom_id.compare(actual, line.remaining_qty) > 0:
                raise UserError(
                    "Actual delivery exceeds the remaining contract milestone quantity."
                )
        return super()._action_done(*args, **kwargs)
