from odoo import Command
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import internal, lock
from odoo.addons.deep_core.services.issued import net_issued


class TransferService:
    def __init__(self, env):
        self.env = env

    def _move(self, kit, line, quantity, source, target, kind, returned=False):
        mo = kit.production_id
        if mo.state in ("draft", "done", "cancel"):
            raise UserError("Move materials only for a confirmed active MO.")
        if line.product_id.tracking != "none" and not line.lot_id:
            raise UserError("Choose the actual component lot/serial.")
        if line.lot_id and (
            line.lot_id.product_id != line.product_id or line.lot_id.company_id != kit.company_id
        ):
            raise UserError("Lot/product/company mismatch.")
        # Reservations for the same MO must move with the physical component kit.
        if kind == "stage":
            for picking in mo.picking_ids.filtered(
                lambda picking: picking.state not in ("done", "cancel")
                and picking.location_id == source
            ):
                picking.move_ids._do_unreserve()
        quants = (
            self.env["stock.quant"]
            .sudo()
            .search(
                [
                    ("product_id", "=", line.product_id.id),
                    ("location_id", "child_of", source.id),
                    ("company_id", "=", kit.company_id.id),
                ]
            )
        )
        lock(quants)
        available = self.env["stock.quant"]._get_available_quantity(
            line.product_id, source, lot_id=line.lot_id or None
        )
        needed = line.uom_id._compute_quantity(quantity, line.product_id.uom_id)
        if line.product_id.uom_id.compare(available, needed) < 0:
            raise UserError("Insufficient actual stock for " + line.product_id.display_name)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": mo.picking_type_id.warehouse_id.int_type_id.id,
                "location_id": source.id,
                "location_dest_id": target.id,
                "origin": kit.name + " / " + kind,
                "company_id": kit.company_id.id,
                "deep_kit_id": kit.id,
                "deep_production_id": mo.id if kind != "stage" else False,
            }
        )
        values = {
            "description_picking_manual": line.product_id.display_name,
            "product_id": line.product_id.id,
            "product_uom": line.uom_id.id,
            "product_uom_qty": quantity,
            "location_id": source.id,
            "location_dest_id": target.id,
            "picking_id": picking.id,
            "company_id": kit.company_id.id,
            "deep_kit_line_id": line.id,
        }
        if kind == "issue":
            values["move_dest_ids"] = [Command.link(line.raw_id.id)]
        if returned:
            values["origin_returned_move_id"] = returned.id
        move = self.env["stock.move"].create(values)
        move._action_confirm()
        move._action_assign()
        move.quantity = quantity
        if line.lot_id:
            move.move_line_ids.write({"lot_id": line.lot_id.id})
        move.picked = True
        result = picking.with_context(skip_backorder=True).button_validate()
        if isinstance(result, dict) and picking.state != "done":
            raise UserError("Complete this native stock transfer before continuing.")
        self.env["deep.audit.event"]._record(
            kit,
            "kit_" + kind,
            reason=str(quantity) + " " + line.uom_id.name + " / " + line.product_id.display_name,
        )
        return move

    def stage(self, kit, lines):
        source = kit.production_id.picking_type_id.warehouse_id.lot_stock_id
        rack = kit._rack()
        for line in lines:
            if line.stage_qty + line.staged_qty > line.requested_qty:
                raise UserError("Staging cannot exceed the requested component quantity.")
            self._move(kit, line, line.stage_qty, source, rack, "stage")
            internal(line).write({"stage_qty": 0})

    def issue(self, kit, lines):
        mo = kit.production_id
        lock(mo)
        for line in lines:
            if (
                line.raw_id.product_uom.compare(
                    net_issued(line.raw_id) + line.issue_qty, line.raw_id.product_uom_qty
                )
                > 0
            ):
                raise UserError(
                    "Cumulative issues from all racks exceed this MO component requirement."
                )
            if line.issue_qty > kit.release_capacity * line.raw_id.unit_factor:
                raise UserError("This issue exceeds the department's per-release capacity.")
            if (
                line.issue_qty > line.rack_qty
                or line.issue_qty + line.issued_qty - line.returned_qty > line.requested_qty
            ):
                raise UserError("Issue only the remaining material actually prepared on this rack.")
            self._move(kit, line, line.issue_qty, kit.rack_id, mo.location_src_id, "issue")
            internal(line).write({"issue_qty": 0})

    def return_material(self, line, quantity, reason):
        kit = line.kit_id
        source = kit.production_id.location_src_id
        # Make unconsumed stock available without modifying posted consumption.
        line.raw_id._do_unreserve()
        origin = line.move_ids.filtered(
            lambda move: move.state == "done"
            and move.location_id == kit.rack_id
            and not move.origin_returned_move_id
        )[:1]
        self._move(kit, line, quantity, source, kit.rack_id, "return", returned=origin)
        line.raw_id._action_assign()
        if kit.state == "issued":
            internal(kit).write({"state": "prepared"})
        self.env["deep.audit.event"]._record(kit, "material_return_reason", reason=reason)
