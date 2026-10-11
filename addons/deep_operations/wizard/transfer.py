from odoo import fields, models
from odoo.addons.deep_core.security import lock, require_role
from odoo.exceptions import UserError


class MaterialReturn(models.TransientModel):
    _name = "deep.kit.return"
    _description = "Actual Return of Unconsumed Department Material"
    kit_line_id = fields.Many2one("deep.material.kit.line", required=True)
    quantity = fields.Float(required=True)
    reason = fields.Text(required=True)

    def action_return(self):
        require_role(self.env, "warehouse", "manager")
        self.ensure_one()
        line = self.kit_line_id
        lock(line.kit_id)
        if self.quantity <= 0 or self.quantity > line.issued_qty - line.returned_qty:
            raise UserError(
                "Return only positive quantities actually issued and not already returned."
            )
        from ..services.transfers import TransferService

        TransferService(self.env).return_material(line, self.quantity, self.reason)
        return {"type": "ir.actions.act_window_close"}


class InstructionAck(models.TransientModel):
    _name = "deep.instruction.ack.wizard"
    _description = "Read and Acknowledge Current Work Instruction"
    workorder_id = fields.Many2one("mrp.workorder", required=True, readonly=True)
    instruction_id = fields.Many2one("deep.work.instruction", required=True)
    body = fields.Html(related="instruction_id.body", readonly=True)
    attachment_ids = fields.Many2many(related="instruction_id.attachment_ids", readonly=True)
    confirmed = fields.Boolean("I have read and understood this instruction")

    def action_acknowledge(self):
        self.ensure_one()
        if not self.confirmed:
            raise UserError("Read the instruction and confirm your acknowledgement.")
        self.env["deep.instruction.ack"].action_acknowledge(
            self.instruction_id.id, self.workorder_id.id
        )
        return {"type": "ir.actions.act_window_close"}
