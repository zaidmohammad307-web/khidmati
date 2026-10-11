from odoo import fields, models
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import lock


class Unit(models.Model):
    _inherit = "deep.production.unit"
    deep_nc_ids = fields.One2many("deep.nonconformance", "unit_id", readonly=True)

    def _deep_blocking_cases(self):
        return self.env["deep.nonconformance"].search(
            [
                ("company_id", "in", self.company_id.ids),
                ("blocking", "=", True),
                ("state", "!=", "closed"),
                "|",
                ("unit_id", "in", self.ids),
                "&",
                ("unit_id", "=", False),
                ("production_id", "in", self.production_id.ids),
            ]
        )

    def _check_release(self):
        super()._check_release()
        for unit in self:
            if unit._deep_blocking_cases():
                raise UserError("An open blocking nonconformance prevents release.")


class Session(models.Model):
    _inherit = "deep.quality.session"

    def _on_failure(self):
        result = super()._on_failure()
        for session in self:
            existing = (
                self.env["deep.nonconformance"]
                .sudo()
                .search([("session_id", "=", session.id)], limit=1)
            )
            if not existing:
                rework = (
                    self.env["deep.rework.order"]
                    .sudo()
                    .search([("session_id", "=", session.id)], limit=1)
                )
                self.env["deep.nonconformance"].sudo().create(
                    {
                        "name": "QA exception / " + session.unit_id.name,
                        "company_id": session.company_id.id,
                        "unit_id": session.unit_id.id,
                        "production_id": session.unit_id.production_id.id,
                        "session_id": session.id,
                        "rework_id": rework.id,
                        "owner_id": session.tester_id.id,
                        "description": session.notes
                        or "Failed or held scanned test; see immutable point results.",
                        "blocking": False,
                    }
                )
        return result


class Move(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        outgoing = self.filtered(
            lambda move: move.location_dest_id.usage == "customer"
            and move.product_id.deep_qa_required
            and move.quantity > 0
        )
        for move in outgoing:
            lots = move.move_line_ids.lot_id
            if not lots:
                raise UserError(
                    "Serialized final products require identified passing units before shipment."
                )
            units = self.env["deep.production.unit"].search(
                [("lot_id", "in", lots.ids), ("company_id", "=", move.company_id.id)]
            )
            if len(units) != len(lots) or any(
                unit.state != "released" or unit.physical_zone != "finished" for unit in units
            ):
                raise UserError("Ship only released units already receipted into finished stock.")
            if units._deep_blocking_cases():
                raise UserError("A blocking quality case prevents outbound shipment.")
        needed = {}
        for line in outgoing.move_line_ids.filtered(lambda line: line.quantity > 0):
            key = (
                line.company_id.id,
                line.product_id.id,
                line.lot_id.id,
                line.location_id.id,
                line.owner_id.id,
                line.package_id.id,
            )
            needed[key] = needed.get(key, 0) + line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id
            )
        quants = (
            self.env["stock.quant"]
            .sudo()
            .search(
                [
                    ("company_id", "in", outgoing.company_id.ids),
                    ("product_id", "in", outgoing.product_id.ids),
                    ("lot_id", "in", outgoing.move_line_ids.lot_id.ids),
                    ("location_id", "in", outgoing.move_line_ids.location_id.ids),
                ]
            )
            if outgoing
            else self.env["stock.quant"]
        )
        if quants:
            lock(quants)
        actual = {}
        for quant in quants:
            key = (
                quant.company_id.id,
                quant.product_id.id,
                quant.lot_id.id,
                quant.location_id.id,
                quant.owner_id.id,
                quant.package_id.id,
            )
            actual[key] = actual.get(key, 0) + quant.quantity
        for key, quantity in needed.items():
            product = self.env["product.product"].browse(key[1])
            if product.uom_id.compare(actual.get(key, 0), quantity) < 0:
                raise UserError(
                    "Insufficient actual serialized finished stock at the shipment source; complete its native warehouse receipt first."
                )
        return super()._action_done(*args, **kwargs)
