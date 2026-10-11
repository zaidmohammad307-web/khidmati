import math
from odoo import Command
from odoo.exceptions import UserError
from ..security import internal, require_role, lock


class SerializationService:
    def __init__(self, env):
        self.env = env

    def generate(self, work, quantity, key):
        require_role(self.env, "operator", "supervisor", "manager")
        work.ensure_one()
        lock(work.production_id)
        if not isinstance(key, str) or not 8 <= len(key) <= 100:
            raise UserError("A serialization request key is required.")
        existing = self.env["deep.serial.request"].search(
            [("production_id", "=", work.production_id.id), ("key", "=", key)]
        )
        if existing:
            if existing.quantity != quantity:
                raise UserError("This request key was used with another quantity.")
            return existing.unit_ids
        if work.operation_id.deep_checkpoint != "serialize" or work.state not in (
            "ready",
            "progress",
        ):
            raise UserError("Generate serials only at the ready S9 checkpoint.")
        if any(w.state != "done" for w in work.blocked_by_workorder_ids):
            raise UserError("Complete preceding operations first.")
        mo = work.production_id
        if mo.product_id.tracking != "serial" or not mo.product_id.deep_family_id:
            raise UserError("Configure serial tracking and a product family sequence.")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, (int, float))
            or not math.isfinite(quantity)
            or int(quantity) != quantity
            or quantity < 1
        ):
            raise UserError("Serial quantity must be a positive whole number.")
        if quantity > mo.product_qty - len(mo.deep_unit_ids):
            raise UserError("Serial count would exceed the planned MO quantity.")
        family = mo.product_id.deep_family_id
        if family.company_id != mo.company_id:
            raise UserError("Family and MO must belong to the same company.")
        rows = []
        for _ in range(int(quantity)):
            name = family.sequence_id.sudo().next_by_id()
            lot = (
                self.env["stock.lot"]
                .sudo()
                .create(
                    {"name": name, "product_id": mo.product_id.id, "company_id": mo.company_id.id}
                )
            )
            rows.append(
                {
                    "name": name,
                    "company_id": mo.company_id.id,
                    "production_id": mo.id,
                    "workorder_id": work.id,
                    "lot_id": lot.id,
                    "operator_id": self.env.uid,
                }
            )
        units = internal(self.env["deep.production.unit"].sudo()).create(rows)
        internal(self.env["deep.serial.request"].sudo()).create(
            {
                "company_id": mo.company_id.id,
                "production_id": mo.id,
                "key": key,
                "quantity": quantity,
                "unit_ids": [Command.set(units.ids)],
            }
        )
        mo.lot_producing_ids = [Command.link(lot.id) for lot in units.lot_id]
        for unit in units:
            self.env["deep.audit.event"]._record(unit, "serial_created", unit=unit)
        return units.with_env(self.env)
