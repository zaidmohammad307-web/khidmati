from odoo import api, fields, models
from odoo.addons.deep_core.security import lock, require_role
from odoo.addons.deep_core.services.issued import net_issued
from odoo.exceptions import UserError


class Picking(models.Model):
    _inherit = "stock.picking"
    deep_kit_id = fields.Many2one("deep.material.kit", check_company=True, copy=True, index=True)


class Move(models.Model):
    _inherit = "stock.move"
    deep_kit_line_id = fields.Many2one(
        "deep.material.kit.line", check_company=True, copy=True, index=True
    )

    def _action_done(self, *args, **kwargs):
        moving = self.filtered(
            lambda move: (
                move.state not in ("done", "cancel") and move.location_dest_id.usage == "internal"
            )
        )
        for raw in moving.move_dest_ids.filtered("raw_material_production_id"):
            arrivals = moving.filtered(
                lambda move: raw in move.move_dest_ids and move.location_dest_id == raw.location_id
            )
            if not arrivals:
                continue
            lock(raw.raw_material_production_id)
            actual = sum(
                move.product_uom._compute_quantity(move.quantity, raw.product_uom)
                for move in arrivals
            )
            if raw.product_uom.compare(net_issued(raw) + actual, raw.product_uom_qty) > 0:
                raise UserError(
                    "Cumulative material issues exceed the native MO component requirement."
                )
        return super()._action_done(*args, **kwargs)


class Production(models.Model):
    _inherit = "mrp.production"
    deep_kit_ids = fields.One2many("deep.material.kit", "production_id")
    deep_shift_report_ids = fields.One2many("deep.shift.report", "production_id")
    deep_handover_ids = fields.One2many("deep.wip.handover", "production_id")
    deep_priority = fields.Selection(
        [("normal", "Normal"), ("high", "High"), ("critical", "Critical")], default="normal"
    )
    deep_promise_date = fields.Date()

    def action_deep_material_kit(self):
        require_role(self.env, "planner", "supervisor", "manager")
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.material.kit",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id},
        }


class Operation(models.Model):
    _inherit = "mrp.routing.workcenter"
    deep_instruction_required = fields.Boolean("Require approved instruction acknowledgement")


class Workorder(models.Model):
    _inherit = "mrp.workorder"

    def action_deep_acknowledge(self):
        self.ensure_one()
        instructions = self.env["deep.work.instruction"]._current_for_work(self)
        acknowledged = (
            self.env["deep.instruction.ack"]
            .search([("workorder_id", "=", self.id), ("user_id", "=", self.env.uid)])
            .instruction_id
        )
        if not instructions:
            raise UserError("No current approved instruction exists for this operation.")
        pending = instructions - acknowledged
        if not pending:
            return {
                "type": "ir.actions.act_window",
                "res_model": "deep.work.instruction",
                "res_id": instructions[0].id,
                "view_mode": "form",
                "views": [(False, "form")],
            }
        instructions = pending
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.instruction.ack.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_workorder_id": self.id,
                "default_instruction_id": instructions[0].id,
            },
        }

    def action_deep_instructions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.work.instruction",
            "view_mode": "list,form",
            "domain": [("operation_ids", "in", self.operation_id.ids), ("state", "=", "approved")],
        }

    def _deep_instruction_check(self):
        for work in self:
            if work.operation_id.deep_instruction_required:
                instructions = self.env["deep.work.instruction"]._current_for_work(work)
                if not instructions:
                    raise UserError(
                        "No current approved work instruction exists for this operation."
                    )
                acknowledged = (
                    self.env["deep.instruction.ack"]
                    .search(
                        [
                            ("workorder_id", "=", work.id),
                            ("user_id", "=", self.env.uid),
                            ("instruction_id", "in", instructions.ids),
                        ]
                    )
                    .instruction_id
                )
                if instructions - acknowledged:
                    raise UserError(
                        "Read and acknowledge every current approved instruction before starting or finishing."
                    )

    def write(self, values):
        if values.get("state") in ("progress", "done"):
            self._deep_instruction_check()
        return super().write(values)

    def button_start(self, *args, **kwargs):
        self._deep_instruction_check()
        return super().button_start(*args, **kwargs)

    def button_finish(self, *args, **kwargs):
        self._deep_instruction_check()
        return super().button_finish(*args, **kwargs)


class Shopfloor(models.AbstractModel):
    _inherit = "deep.shopfloor"

    @api.model
    def board(self, offset=0):
        rows = super().board(offset)
        works = self.env["mrp.workorder"].browse(
            [station["id"] for row in rows for station in row["stations"]]
        )
        required = {work.id: work.operation_id.deep_instruction_required for work in works}
        for row in rows:
            for station in row["stations"]:
                station["instruction_required"] = required[station["id"]]
        return rows
