from odoo import Command, fields, models
from odoo.addons.deep_core.security import internal, lock, require_role
from odoo.exceptions import UserError


class Unit(models.Model):
    _inherit = "deep.production.unit"
    session_ids = fields.One2many("deep.quality.session", "unit_id", readonly=True)

    def _check_release(self):
        super()._check_release()
        for u in self:
            latest = u.session_ids.filtered(lambda s: s.state == "done").sorted("id", reverse=True)[
                :1
            ]
            if (
                not latest
                or latest.outcome != "pass"
                or latest.template_id != u.product_id.deep_quality_template_id
            ):
                raise UserError("The latest scanned test must pass the current template.")

    def action_prepare_selected(self):
        require_role(self.env, "operator", "supervisor", "manager")
        if not self or len(self.production_id) != 1 or any(u.state != "passed" for u in self):
            raise UserError("Select passing serials from one MO.")
        mo = self.production_id
        lock(mo)
        mo.write({"lot_producing_ids": [Command.set(self.lot_id.ids)], "qty_producing": len(self)})
        mo.workorder_ids.filtered(
            lambda w: w.deep_checkpoint == "test" and w.state != "done"
        ).button_finish()
        return True

    def action_finish_selected(self):
        require_role(self.env, "operator", "supervisor", "manager")
        if not self or len(self.production_id) != 1 or any(u.state != "released" for u in self):
            raise UserError("Select released units from one MO.")
        mo = self.production_id
        lock(mo)
        mo.write({"lot_producing_ids": [Command.set(self.lot_id.ids)], "qty_producing": len(self)})
        mo.workorder_ids.filtered(
            lambda w: w.deep_checkpoint == "release" and w.state != "done"
        ).button_finish()
        return mo.button_mark_done()


class Workorder(models.Model):
    _inherit = "mrp.workorder"

    def write(self, vals):
        if vals.get("state") == "done":
            self._deep_check_quality()
        return super().write(vals)

    def _deep_check_quality(self):
        for w in self:
            units = w.production_id.deep_unit_ids.filtered(
                lambda u: u.lot_id in w.production_id.lot_producing_ids
            )
            if w.deep_checkpoint == "test" and (
                not units or any(u.state not in ("passed", "released") for u in units)
            ):
                raise UserError("Every selected serial must pass its scanned S12 test.")
            if w.deep_checkpoint == "release" and (
                not units or any(u.state != "released" for u in units)
            ):
                raise UserError("Release every selected serial using the validated S13 action.")
        return True

    def button_finish(self):
        self._deep_check_quality()
        return super().button_finish()


class Production(models.Model):
    _inherit = "mrp.production"

    def _deep_gate(self):
        for mo in self.filtered(lambda p: p.product_id.deep_qa_required):
            units = mo.deep_unit_ids.filtered(lambda u: u.lot_id in mo.lot_producing_ids)
            if (
                not units
                or len(units) != len(mo.lot_producing_ids)
                or len(units) != mo.qty_producing
            ):
                raise UserError("Every produced serial must have a validated unit identity.")
            if any(u.state != "released" for u in units):
                raise UserError("Failed, held or untested serials cannot enter finished stock.")
            for u in units:
                latest = u.session_ids.filtered(lambda s: s.state == "done").sorted(
                    "id", reverse=True
                )[:1]
                if (
                    not latest
                    or latest.outcome != "pass"
                    or latest.template_id != u.product_id.deep_quality_template_id
                ):
                    raise UserError("Latest scanned result must pass the current quality template.")
                if "rework_ids" in u._fields and any(
                    r.state not in ("closed", "scrapped") for r in u.rework_ids
                ):
                    raise UserError("An open rework record blocks receipt.")
            if any(w.state != "done" for w in mo.workorder_ids):
                raise UserError("All required stations must finish before receipt.")
            for raw in mo.move_raw_ids.filtered(lambda m: m.state not in ("cancel", "done")):
                needed = mo.qty_producing * raw.unit_factor
                if raw.product_uom.compare(raw.quantity, needed) < 0 or not raw.picked:
                    raise UserError("Record actual component consumption before receipt.")

    def write(self, vals):
        if vals.get("state") == "done":
            self._deep_gate()
        return super().write(vals)

    def button_mark_done(self):
        self._deep_gate()
        return super().button_mark_done()

    def _post_inventory(self, *args, **kwargs):
        self._deep_gate()
        result = super()._post_inventory(*args, **kwargs)
        for mo in self:
            units = mo.deep_unit_ids.filtered(lambda u: u.lot_id in mo.lot_producing_ids)
            internal(units.sudo()).write({"physical_zone": "finished"})
            for u in units:
                self.env["deep.audit.event"]._record(u, "native_finished_receipt", unit=u)
        return result

    def _split_productions(self, *args, **kwargs):
        result = super()._split_productions(*args, **kwargs)
        for mo in self:
            pending = mo.deep_unit_ids.filtered(lambda u: u.lot_id not in mo.lot_producing_ids)
            for backorder in (
                (result - self)
                .filtered(lambda p: p.production_group_id == mo.production_group_id)
                .sorted("id")
            ):
                units = pending[: int(backorder.product_qty)]
                internal(units.sudo()).write({"production_id": backorder.id, "batch_id": False})
                backorder.lot_producing_ids = [Command.set(units.lot_id.ids)]
                pending -= units
        return result


class Move(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        self.filtered(
            lambda m: (
                m.production_id and m.product_id == m.production_id.product_id and not m.scrap_id
            )
        ).production_id._deep_gate()
        return super()._action_done(*args, **kwargs)
