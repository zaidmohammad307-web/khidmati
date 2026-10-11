from odoo import fields, models
from odoo.exceptions import UserError

from ..security import require_role
from ..services.serialization import SerializationService


class SerialRequest(models.Model):
    _name = "deep.serial.request"
    _inherit = "deep.service.result"
    _description = "Idempotent Serialization Request"
    company_id = fields.Many2one("res.company", required=True)
    production_id = fields.Many2one("mrp.production", required=True, ondelete="restrict")
    key = fields.Char(required=True)
    quantity = fields.Integer(required=True)
    unit_ids = fields.Many2many("deep.production.unit")
    _key = models.Constraint("UNIQUE(production_id, key)", "Serialization request already exists.")


class Production(models.Model):
    _inherit = "mrp.production"
    deep_unit_ids = fields.One2many("deep.production.unit", "production_id", readonly=True)
    deep_batch_ids = fields.One2many("deep.production.batch", "production_id")
    deep_parent_id = fields.Many2one("mrp.production", check_company=True)

    def action_confirm(self):
        result = super().action_confirm()
        for mo in self:
            for picking in mo.picking_ids.filtered(
                lambda p: p.location_dest_id == mo.location_src_id
            ):
                owners = picking.move_ids.move_dest_ids.raw_material_production_id
                if owners == mo:
                    picking.deep_production_id = mo
        return result

    def action_deep_issue(self):
        self.ensure_one()
        require_role(self.env, "warehouse", "manager")
        wizard = self.env["deep.material.issue"].create({"production_id": self.id})
        wizard._prepare()
        return {
            "type": "ir.actions.act_window",
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_deep_consume(self):
        self.ensure_one()
        require_role(self.env, "operator", "supervisor", "manager")
        wizard = self.env["deep.material.issue"].create(
            {"production_id": self.id, "mode": "consume"}
        )
        wizard._prepare()
        return {
            "type": "ir.actions.act_window",
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def deep_material_status(self):
        self.ensure_one()
        self.check_access("read")
        issues = self.env["stock.move"].search(
            [
                ("state", "=", "done"),
                "|",
                ("picking_id.deep_production_id", "=", self.id),
                ("origin_returned_move_id.picking_id.deep_production_id", "=", self.id),
            ]
        )
        scraps = self.env["stock.move"].search(
            [("scrap_id.production_id", "=", self.id), ("state", "=", "done")]
        )
        rows = []
        for raw in self.move_raw_ids:
            moves = issues.filtered(
                lambda move: (
                    raw in move.move_dest_ids or raw in move.origin_returned_move_id.move_dest_ids
                )
            )

            def convert(move):
                return move.product_uom._compute_quantity(move.quantity, raw.product_uom)

            issued = sum(convert(m) for m in moves if not m.origin_returned_move_id)
            returned = sum(convert(m) for m in moves if m.origin_returned_move_id)
            scrapped = sum(convert(m) for m in scraps if m.product_id == raw.product_id)
            rows.append(
                {
                    "id": raw.id,
                    "item": raw.product_id.default_code or raw.product_id.name,
                    "planned": raw.product_uom_qty,
                    "reserved": raw.quantity if raw.state != "done" else 0,
                    "issued": issued,
                    "consumed": raw.quantity if raw.state == "done" else 0,
                    "returned": returned,
                    "scrapped": scrapped,
                    "remaining": max(0, raw.product_uom_qty - issued + returned),
                    "variance": issued - raw.product_uom_qty,
                }
            )
        return rows


class Workorder(models.Model):
    _inherit = "mrp.workorder"
    deep_checkpoint = fields.Selection(related="operation_id.deep_checkpoint")
    deep_operator_id = fields.Many2one("res.users", copy=False)

    def action_deep_serialize(self, quantity=1, request_key=""):
        self.ensure_one()
        return SerializationService(self.env).generate(self, quantity, request_key).ids

    def write(self, vals):
        if vals.get("state") == "done":
            for work in self:
                if any(p.state != "done" for p in work.blocked_by_workorder_ids):
                    raise UserError("Complete preceding operations first.")
                if (
                    work.deep_checkpoint == "serialize"
                    and len(work.production_id.deep_unit_ids) < work.production_id.qty_producing
                ):
                    raise UserError("Serialization at S9 is required.")
        return super().write(vals)

    def button_start(self, *args, **kwargs):
        require_role(self.env, "operator", "supervisor", "manager")
        for w in self:
            if any(p.state != "done" for p in w.blocked_by_workorder_ids):
                raise UserError("Complete preceding operations first.")
            if (
                w.deep_operator_id
                and w.deep_operator_id != self.env.user
                and not self.env.su
                and not self.env.user.has_group("deep_core.group_manager")
            ):
                raise UserError("This work order is assigned to another operator.")
        self.write({"deep_operator_id": self.env.uid})
        return super().button_start(*args, **kwargs)

    def button_finish(self):
        require_role(self.env, "operator", "supervisor", "manager")
        for w in self:
            if (
                w.deep_operator_id
                and w.deep_operator_id != self.env.user
                and not self.env.su
                and not self.env.user.has_group("deep_core.group_manager")
            ):
                raise UserError("Only the assigned operator can finish this work order.")
            if any(p.state != "done" for p in w.blocked_by_workorder_ids):
                raise UserError("Complete preceding operations first.")
            if (
                w.deep_checkpoint == "serialize"
                and len(w.production_id.deep_unit_ids) < w.production_id.qty_producing
            ):
                raise UserError("Create the required serials at S9 first.")
        return super().button_finish()


class Picking(models.Model):
    _inherit = "stock.picking"
    deep_production_id = fields.Many2one(
        "mrp.production", check_company=True, index=True, copy=True
    )

    def button_validate(self):
        result = super().button_validate()
        for p in self.filtered(lambda p: p.deep_production_id and p.state == "done"):
            self.env["deep.audit.event"]._record(
                p, "warehouse_actual_issue", reason=p.deep_production_id.name
            )
        return result
