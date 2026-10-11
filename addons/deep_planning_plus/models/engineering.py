import hashlib
import json

from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_internal, require_role
from odoo.exceptions import AccessError, UserError


class Change(models.Model):
    _name = "deep.engineering.change"
    _description = "Approved BOM / Routing Revision"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(required=True)
    source_bom_id = fields.Many2one("mrp.bom", required=True, check_company=True)
    proposed_bom_id = fields.Many2one("mrp.bom", readonly=True, check_company=True, copy=False)
    revision = fields.Char(required=True)
    effective_date = fields.Date(default=fields.Date.context_today, required=True)
    reason = fields.Text(required=True)
    impact = fields.Text()
    attachment_ids = fields.Many2many("ir.attachment")
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_digest = fields.Char(readonly=True)
    state = fields.Selection(
        [(key, key.title()) for key in ["draft", "review", "approved", "applied", "cancel"]],
        default="draft",
    )
    _protected_fields = {"state", "proposed_bom_id", "approved_by", "approved_digest"}

    def write(self, values):
        if any(change.state != "draft" for change in self) and set(values) & {
            "source_bom_id",
            "revision",
            "effective_date",
            "reason",
            "impact",
        }:
            raise AccessError("Submitted engineering change identity is frozen.")
        return super().write(values)

    def _digest(self):
        self.ensure_one()
        bom = self.proposed_bom_id
        payload = {
            "bom": [bom.id, str(bom.write_date)],
            "lines": [[line.id, str(line.write_date)] for line in bom.bom_line_ids.sorted("id")],
            "operations": [
                [operation.id, str(operation.write_date)]
                for operation in bom.operation_ids.sorted("id")
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def action_clone(self):
        require_role(self.env, "planner", "manager")
        for change in self:
            lock(change)
            if change.state != "draft" or change.proposed_bom_id:
                raise UserError("Clone once on a new draft engineering change.")
            source = change.source_bom_id
            if source.company_id != change.company_id or change.revision == source.deep_revision:
                raise UserError("Choose a new revision in the same company.")
            bom = source.copy(
                {
                    "active": False,
                    "deep_revision": change.revision,
                    "deep_effective_date": change.effective_date,
                }
            )
            internal(change).write({"proposed_bom_id": bom.id})
        return True

    def action_open_bom(self):
        self.ensure_one()
        if not self.proposed_bom_id:
            raise UserError("Clone the proposed revision first.")
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom",
            "res_id": self.proposed_bom_id.id,
            "view_mode": "form",
        }

    def action_submit(self):
        require_role(self.env, "planner", "manager")
        if any(
            not change.proposed_bom_id or not change.proposed_bom_id.bom_line_ids for change in self
        ):
            raise UserError("Provide a proposed BOM with components.")
        return self._transition(["draft"], "review")

    def action_approve(self):
        require_role(self.env, "manager")
        for change in self:
            internal(change).write(
                {"approved_by": self.env.uid, "approved_digest": change._digest()}
            )
        return self._transition(["review"], "approved", "Manager approved BOM/routing revision")

    def action_apply(self):
        require_role(self.env, "manager")
        for change in self:
            lock(change)
            lock(change.source_bom_id)
            lock(change.proposed_bom_id)
            if change.state != "approved" or change.effective_date > fields.Date.context_today(
                change
            ):
                raise UserError("Apply an approved revision on or after its effective date.")
            if change._digest() != change.approved_digest:
                raise UserError("The proposed BOM changed after approval.")
            internal(change.source_bom_id).write({"active": False})
            internal(change.proposed_bom_id).write({"active": True})
        return self._transition(
            ["approved"],
            "applied",
            "New orders select new revision; existing MOs retain their original BOM",
        )


class Bom(models.Model):
    _inherit = "mrp.bom"
    deep_eco_target_ids = fields.One2many("deep.engineering.change", "proposed_bom_id", copy=False)

    def _deep_revision_guard(self, values=None):
        frozen = self.deep_eco_target_ids.filtered(
            lambda change: change.state in ("approved", "applied")
        )
        if frozen:
            if values is not None and set(values) == {"active"}:
                require_internal(self.env)
            else:
                raise AccessError(
                    "Approved BOM revisions are frozen. Create a new engineering change."
                )

    def write(self, values):
        self._deep_revision_guard(values)
        return super().write(values)

    def unlink(self):
        self._deep_revision_guard()
        return super().unlink()


class BomLine(models.Model):
    _inherit = "mrp.bom.line"

    @api.model_create_multi
    def create(self, values):
        self.env["mrp.bom"].browse(
            [value["bom_id"] for value in values if value.get("bom_id")]
        )._deep_revision_guard()
        return super().create(values)

    def write(self, values):
        self.bom_id._deep_revision_guard()
        if values.get("bom_id"):
            self.env["mrp.bom"].browse(values["bom_id"])._deep_revision_guard()
        return super().write(values)

    def unlink(self):
        self.bom_id._deep_revision_guard()
        return super().unlink()


class Operation(models.Model):
    _inherit = "mrp.routing.workcenter"

    @api.model_create_multi
    def create(self, values):
        self.env["mrp.bom"].browse(
            [value["bom_id"] for value in values if value.get("bom_id")]
        )._deep_revision_guard()
        return super().create(values)

    def write(self, values):
        self.bom_id._deep_revision_guard()
        if values.get("bom_id"):
            self.env["mrp.bom"].browse(values["bom_id"])._deep_revision_guard()
        return super().write(values)

    def unlink(self):
        self.bom_id._deep_revision_guard()
        return super().unlink()
