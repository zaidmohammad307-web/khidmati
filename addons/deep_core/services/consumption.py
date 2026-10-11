from odoo.exceptions import UserError

from ..security import lock, require_role


class ConsumptionService:
    def __init__(self, env):
        self.env = env

    def record(self, production, lines):
        require_role(self.env, "operator", "supervisor", "manager")
        lock(production)
        if production.state not in ("confirmed", "progress", "to_close"):
            raise UserError("Record actual consumption on an active manufacturing order.")
        if not lines.filtered(lambda planning_line: planning_line.quantity > 0):
            raise UserError("Enter actual consumed quantities.")
        for line in lines:
            raw = line.raw_id
            if raw.raw_material_production_id != production or raw.product_id != line.product_id:
                raise UserError("Component and manufacturing order mismatch.")
            if line.quantity < 0 or line.quantity > raw.product_uom_qty:
                raise UserError("Consumption must be within the component requirement.")
            if line.product_id.tracking != "none" and line.quantity and not line.lot_id:
                raise UserError("Select actual consumed component lots.")
            if line.lot_id and (
                line.lot_id.product_id != line.product_id
                or line.lot_id.company_id != production.company_id
            ):
                raise UserError("Consumed lot/product/company mismatch.")
            quants = self.env["stock.quant"].search(
                [("product_id", "=", line.product_id.id), ("location_id", "=", raw.location_id.id)]
                + ([("lot_id", "=", line.lot_id.id)] if line.lot_id else [])
            )
            actual = sum(quants.mapped("quantity"))
            needed = raw.product_uom._compute_quantity(line.quantity, line.product_id.uom_id)
            if actual < needed:
                raise UserError(
                    "The actual pre-production location lacks " + line.product_id.display_name
                )
            raw._set_quantity_done(line.quantity)
            if line.lot_id:
                raw.move_line_ids.write({"lot_id": line.lot_id.id})
            raw.picked = bool(line.quantity)
        self.env["deep.audit.event"]._record(
            production,
            "actual_consumption_recorded",
            reason="Operator entered actual quantities; stock posts at native completion",
        )
        return {"type": "ir.actions.act_window_close"}
