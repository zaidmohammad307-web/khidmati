from odoo import Command, fields, models
from odoo.exceptions import UserError

from ..security import lock, require_role
from ..services.consumption import ConsumptionService
from ..services.issued import net_issued


class Issue(models.TransientModel):
    _name = "deep.material.issue"
    _description = "Actual Warehouse Material Issue"
    production_id = fields.Many2one("mrp.production", required=True)
    mode = fields.Selection(
        [("issue", "Warehouse Issue"), ("consume", "Production Consumption")],
        default="issue",
        required=True,
    )
    line_ids = fields.One2many("deep.material.issue.line", "wizard_id")

    def _prepare(self):
        self.line_ids = [
            Command.create(
                {"raw_id": m.id, "product_id": m.product_id.id, "planned": m.product_uom_qty}
            )
            for m in self.production_id.move_raw_ids
            if m.state not in ("done", "cancel")
        ]

    def action_issue(self):
        self.ensure_one()
        if self.mode == "consume":
            return ConsumptionService(self.env).record(self.production_id, self.line_ids)
        require_role(self.env, "warehouse", "manager")
        mo = self.production_id
        lock(mo)
        wh = mo.picking_type_id.warehouse_id
        source, target = wh.lot_stock_id, mo.location_src_id
        if source == target:
            raise UserError(
                "Enable multi-step manufacturing with a separate pre-production location."
            )
        selected = self.line_ids.filtered(lambda planning_line: planning_line.quantity > 0)
        if not selected:
            raise UserError("Enter actual quantities to issue.")
        if any(
            planning_line.quantity < 0 or planning_line.quantity > planning_line.planned
            for planning_line in self.line_ids
        ):
            raise UserError("Actual quantity must be between zero and its planned requirement.")
        if mo.state in ("draft", "done", "cancel"):
            raise UserError("Issue only for a confirmed active MO.")
        if len(selected.raw_id) != len(selected):
            raise UserError("One actual issue line per MO component is required.")
        for line in selected:
            if (
                line.raw_id.product_uom.compare(
                    line.quantity + net_issued(line.raw_id), line.raw_id.product_uom_qty
                )
                > 0
            ):
                raise UserError("This issue exceeds the remaining native MO component requirement.")
        # Use the upstream pick-components chain whenever it already exists.
        pickings = mo.picking_ids.filtered(
            lambda p: (
                p.state not in ("done", "cancel")
                and p.location_id == source
                and p.location_dest_id == target
            )
        )
        picking = pickings[:1]
        if not picking:
            picking = self.env["stock.picking"].create(
                {
                    "picking_type_id": wh.int_type_id.id,
                    "location_id": source.id,
                    "location_dest_id": target.id,
                    "origin": mo.name,
                    "company_id": mo.company_id.id,
                    "deep_production_id": mo.id,
                }
            )
        picking.deep_production_id = mo
        picking.move_ids._do_unreserve()
        for move in picking.move_ids:
            move.quantity = 0
        for line in selected:
            if (
                line.raw_id.raw_material_production_id != mo
                or line.product_id != line.raw_id.product_id
            ):
                raise UserError("This issue line does not belong to this MO component.")
            if line.product_id.tracking != "none" and not line.lot_id:
                raise UserError("Select an actual component lot/serial.")
            if line.lot_id and (
                line.lot_id.product_id != line.product_id or line.lot_id.company_id != mo.company_id
            ):
                raise UserError("Lot/product/company mismatch.")
            available = self.env["stock.quant"]._get_available_quantity(
                line.product_id, source, lot_id=line.lot_id or None
            )
            needed = line.raw_id.product_uom._compute_quantity(
                line.quantity, line.product_id.uom_id
            )
            if available < needed:
                raise UserError("Insufficient actual stock for " + line.product_id.display_name)
            move = picking.move_ids.filtered(
                lambda m: line.raw_id in m.move_dest_ids and m.state not in ("done", "cancel")
            )[:1]
            if not move:
                move = self.env["stock.move"].create(
                    {
                        "description_picking_manual": line.product_id.display_name,
                        "product_id": line.product_id.id,
                        "product_uom": line.raw_id.product_uom.id,
                        "product_uom_qty": line.quantity,
                        "location_id": source.id,
                        "location_dest_id": target.id,
                        "picking_id": picking.id,
                        "company_id": mo.company_id.id,
                        "move_dest_ids": [Command.link(line.raw_id.id)],
                    }
                )
                move._action_confirm()
            move._action_assign()
            move.quantity = line.quantity
            if line.lot_id:
                move.move_line_ids.write({"lot_id": line.lot_id.id})
            move.picked = True
        result = picking.with_context(skip_backorder=True).button_validate()
        return (
            result
            if isinstance(result, dict)
            else {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "res_id": picking.id,
                "view_mode": "form",
            }
        )


class Line(models.TransientModel):
    _name = "deep.material.issue.line"
    _description = "Actual Component Issue Line"
    wizard_id = fields.Many2one("deep.material.issue", required=True, ondelete="cascade")
    raw_id = fields.Many2one("stock.move", required=True)
    product_id = fields.Many2one("product.product", required=True)
    planned = fields.Float(readonly=True)
    quantity = fields.Float()
    lot_id = fields.Many2one("stock.lot")
