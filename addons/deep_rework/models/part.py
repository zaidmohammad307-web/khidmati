from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_internal
from odoo.exceptions import UserError


class Part(models.Model):
    _name = "deep.rework.part"
    _description = "Rework Component Stock Movement"
    _check_company_auto = True
    rework_id = fields.Many2one("deep.rework.order", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="rework_id.company_id", store=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    lot_id = fields.Many2one("stock.lot", check_company=True)
    direction = fields.Selection(
        [("remove", "Remove to Hold"), ("install", "Install from Stock")], required=True
    )
    quantity = fields.Float(default=1, required=True)
    move_id = fields.Many2one("stock.move", readonly=True, check_company=True)
    _positive = models.Constraint("CHECK(quantity>0)", "Part quantity must be positive.")

    @api.model_create_multi
    def create(self, vals):
        orders = self.env["deep.rework.order"].browse([v["rework_id"] for v in vals])
        orders._assignment()
        if any(r.state != "repairing" for r in orders):
            raise UserError("Record parts during active repairs.")
        if any(v.get("move_id") for v in vals):
            require_internal(self.env)
        return super().create(vals)

    def write(self, vals):
        self.rework_id._assignment()
        if "move_id" in vals:
            require_internal(self.env)
        if any(p.move_id for p in self):
            raise UserError("Transferred part records are locked.")
        return super().write(vals)

    def unlink(self):
        self.rework_id._assignment()
        if any(p.move_id for p in self):
            raise UserError("Transferred part history is permanent.")
        return super().unlink()

    def action_transfer(self):
        for p in self:
            p.rework_id._assignment()
            lock(p)
            if p.move_id or p.rework_id.state != "repairing":
                raise UserError("Part movement is already recorded or repair is inactive.")
            mo = p.rework_id.unit_id.production_id
            if mo.state in ("done", "cancel"):
                raise UserError(
                    "Use a native finished-goods repair workflow after production receipt."
                )
            wh = mo.picking_type_id.warehouse_id
            hold = self.env["stock.location"].search(
                [
                    ("company_id", "=", p.company_id.id),
                    ("location_id", "=", wh.view_location_id.id),
                    ("name", "=", "Quality Hold"),
                ],
                limit=1,
            )
            if not hold:
                raise UserError("Configure this warehouse’s Quality Hold location.")
            source = mo.location_src_id if p.direction == "remove" else wh.lot_stock_id
            destination = hold if p.direction == "remove" else mo.location_src_id
            if p.product_id.tracking != "none" and not p.lot_id:
                raise UserError("Select the actual part lot/serial.")
            if p.lot_id and p.lot_id.product_id != p.product_id:
                raise UserError("Lot and replacement product mismatch.")
            raw = mo.move_raw_ids.filtered(
                lambda m: m.product_id == p.product_id and m.state not in ("done", "cancel")
            )
            raw._do_unreserve()
            if (
                self.env["stock.quant"]._get_available_quantity(
                    p.product_id, source, lot_id=p.lot_id or None
                )
                < p.quantity
            ):
                raise UserError("The source location does not contain enough actual stock.")
            move = self.env["stock.move"].create(
                {
                    "name": p.rework_id.name,
                    "product_id": p.product_id.id,
                    "product_uom": p.product_id.uom_id.id,
                    "product_uom_qty": p.quantity,
                    "location_id": source.id,
                    "location_dest_id": destination.id,
                    "company_id": p.company_id.id,
                }
            )
            move._action_confirm()
            move._action_assign()
            move.quantity = p.quantity
            if p.lot_id:
                move.move_line_ids.write({"lot_id": p.lot_id.id})
            move.picked = True
            move._action_done()
            internal(p).write({"move_id": move.id})
            raw._action_assign()
            self.env["deep.audit.event"]._record(
                p.rework_id,
                "replacement_" + p.direction,
                reason=p.product_id.display_name,
                unit=p.rework_id.unit_id,
            )
        return True
