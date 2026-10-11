from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_role, lock


class Instruction(models.Model):
    _name = "deep.work.instruction"
    _description = "Versioned Work Instruction"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    version = fields.Integer(required=True, default=1)
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "review", "approved", "obsolete"]], default="draft"
    )
    operation_ids = fields.Many2many("mrp.routing.workcenter", check_company=True)
    body = fields.Html(sanitize=True)
    attachment_ids = fields.Many2many("ir.attachment")
    effective_date = fields.Date(default=fields.Date.context_today, required=True)
    valid_until = fields.Date()
    approval_note = fields.Text()
    approved_by = fields.Many2one("res.users", readonly=True)
    _version = models.Constraint(
        "UNIQUE(company_id,code,version)", "Instruction version already exists."
    )
    _positive = models.Constraint("CHECK(version>0)", "Version must be positive.")
    _protected_fields = {"state", "approved_by"}

    def write(self, values):
        if any(record.state in ("approved", "obsolete") for record in self) and set(values) - {
            "state"
        }:
            raise AccessError("Approved instructions are immutable; create a new version.")
        return super().write(values)

    @api.model
    def _current_for_work(self, work):
        today = fields.Date.context_today(work)
        records = self.search(
            [
                ("company_id", "=", work.company_id.id),
                ("operation_ids", "in", work.operation_id.ids),
                ("state", "=", "approved"),
                ("effective_date", "<=", today),
                "|",
                ("valid_until", "=", False),
                ("valid_until", ">=", today),
            ],
            order="code,version desc",
        )
        selected = self.browse()
        seen = set()
        for record in records:
            if record.code not in seen:
                selected |= record
                seen.add(record.code)
        return selected

    @api.constrains("effective_date", "valid_until")
    def _dates(self):
        if any(
            record.valid_until and record.valid_until < record.effective_date for record in self
        ):
            raise UserError("Instruction expiry cannot precede its effective date.")

    def action_submit(self):
        require_role(self.env, "planner", "supervisor", "manager")
        if any(not record.body and not record.attachment_ids for record in self):
            raise UserError("Provide instruction content or an attachment.")
        return self._transition(["draft"], "review")

    def action_approve(self):
        require_role(self.env, "supervisor", "manager")
        for record in self:
            lock(record)
            if record.state != "review":
                raise UserError("Approve an instruction submitted for review.")
            previous = self.search(
                [
                    ("company_id", "=", record.company_id.id),
                    ("code", "=", record.code),
                    ("state", "=", "approved"),
                    ("id", "!=", record.id),
                ]
            )
            lock(previous)
            if any(old.version >= record.version for old in previous):
                raise UserError("Approve a newer instruction version.")
            for old in previous.filtered(
                lambda old: record.effective_date <= fields.Date.context_today(record)
            ):
                old._transition(
                    ["approved"], "obsolete", "Superseded by version " + str(record.version)
                )
            if not record.approval_note:
                raise UserError("Record the approval note.")
            if any(op.company_id != record.company_id for op in record.operation_ids):
                raise UserError("Instruction operations must belong to the same company.")
            internal(record).write({"approved_by": self.env.uid})
        return self._transition(["review"], "approved", "Instruction approved")

    def action_obsolete(self):
        require_role(self.env, "supervisor", "manager")
        return self._transition(["approved"], "obsolete")

    def action_revision(self):
        require_role(self.env, "planner", "supervisor", "manager")
        self.ensure_one()
        next_version = (
            max(
                self.search(
                    [("company_id", "=", self.company_id.id), ("code", "=", self.code)]
                ).mapped("version")
            )
            + 1
        )
        record = self.copy(
            {
                "state": "draft",
                "version": next_version,
                "approved_by": False,
                "approval_note": False,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": record.id,
            "view_mode": "form",
        }


class Acknowledgement(models.Model):
    _name = "deep.instruction.ack"
    _description = "Operator Work Instruction Acknowledgement"
    _inherit = "deep.service.result"
    instruction_id = fields.Many2one("deep.work.instruction", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="instruction_id.company_id", store=True)
    user_id = fields.Many2one("res.users", required=True)
    workorder_id = fields.Many2one("mrp.workorder", required=True)
    at = fields.Datetime(default=fields.Datetime.now)
    _unique = models.Constraint(
        "UNIQUE(instruction_id,user_id,workorder_id)", "Already acknowledged."
    )

    @api.model
    def action_acknowledge(self, instruction_id, workorder_id):
        require_role(self.env, "operator", "supervisor", "manager")
        instruction = self.env["deep.work.instruction"].browse(instruction_id).exists()
        work = self.env["mrp.workorder"].browse(workorder_id).exists()
        instruction.check_access("read")
        work.check_access("write")
        if (
            not instruction
            or not work
            or instruction.company_id != self.env.company
            or work.company_id != self.env.company
            or instruction.state != "approved"
            or work.operation_id not in instruction.operation_ids
        ):
            raise UserError("Select a current approved instruction for this operation.")
        if instruction not in self.env["deep.work.instruction"]._current_for_work(work):
            raise UserError("The instruction is outside its validity dates.")
        existing = self.search(
            [
                ("instruction_id", "=", instruction.id),
                ("workorder_id", "=", work.id),
                ("user_id", "=", self.env.uid),
            ]
        )
        if not existing:
            # Lock the work order so repeated acknowledgements cannot race.
            from odoo.addons.deep_core.security import lock

            lock(work)
            existing = self.search(
                [
                    ("instruction_id", "=", instruction.id),
                    ("workorder_id", "=", work.id),
                    ("user_id", "=", self.env.uid),
                ]
            )
            if not existing:
                existing = internal(self.sudo()).create(
                    {
                        "instruction_id": instruction.id,
                        "workorder_id": work.id,
                        "user_id": self.env.uid,
                    }
                )
                self.env["deep.audit.event"]._record(
                    work,
                    "instruction_acknowledged",
                    reason=instruction.code + " v" + str(instruction.version),
                )
        return existing.id
