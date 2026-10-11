from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_internal, require_role, lock
from odoo.addons.deep_core.services.export import export_xlsx
from ..services.rework import ReworkService


class Rework(models.Model):
    _name = "deep.rework.order"
    _description = "Defective Product Rework"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "priority desc,id desc"
    name = fields.Char(default="New", required=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True)
    unit_id = fields.Many2one(
        "deep.production.unit", required=True, check_company=True, ondelete="restrict", index=True
    )
    session_id = fields.Many2one(
        "deep.quality.session", required=True, check_company=True, ondelete="restrict"
    )
    technician_id = fields.Many2one("res.users", tracking=True, domain="[('share','=',False)]")
    priority = fields.Selection([("0", "Normal"), ("1", "High"), ("2", "Critical")], default="0")
    state = fields.Selection(
        [
            (s, s.replace("_", " ").title())
            for s in [
                "new",
                "assigned",
                "diagnosis",
                "waiting_parts",
                "repairing",
                "ready",
                "retesting",
                "closed",
                "scrapped",
            ]
        ],
        default="new",
        readonly=True,
        required=True,
        tracking=True,
        index=True,
    )
    description = fields.Text()
    root_cause = fields.Text()
    corrective_action = fields.Text()
    disposition = fields.Selection([("repair", "Repair"), ("scrap", "Scrap")], default="repair")
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    retest_id = fields.Many2one("deep.quality.session", readonly=True, check_company=True)
    part_ids = fields.One2many("deep.rework.part", "rework_id")
    attachment_ids = fields.Many2many("ir.attachment")
    _session = models.Constraint(
        "UNIQUE(session_id)", "Failed session already has a rework record."
    )
    _number = models.Constraint("UNIQUE(company_id,name)", "Rework number already exists.")

    @api.model_create_multi
    def create(self, vals):
        require_internal(self.env)
        for v in vals:
            v["name"] = self.env["ir.sequence"].sudo().next_by_code("deep.rework")
        return super().create(vals)

    def write(self, vals):
        if set(vals) & {
            "name",
            "state",
            "unit_id",
            "session_id",
            "company_id",
            "started_at",
            "completed_at",
            "retest_id",
        }:
            require_internal(self.env)
        if "technician_id" in vals:
            require_role(self.env, "supervisor", "manager")
        if any(r.state in ("closed", "scrapped") for r in self):
            raise AccessError("Completed rework history is locked.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Rework genealogy is permanent.")

    def _assignment(self):
        require_role(self.env, "technician", "supervisor", "manager")
        if (
            not self.env.su
            and not self.env.user.has_group("deep_core.group_manager")
            and any(r.technician_id != self.env.user for r in self)
        ):
            raise AccessError("Only the assigned technician may execute this repair.")

    def _advance(self, allowed, target):
        for r in self:
            lock(r)
            if r.state not in allowed:
                raise UserError("Rework is not in the expected state.")
            previous = r.state
            internal(r).write({"state": target})
            self.env["deep.audit.event"]._record(
                r, "rework_" + target, previous, target, unit=r.unit_id
            )
        return True

    def action_assign(self):
        require_role(self.env, "supervisor", "manager")
        if any(not r.technician_id for r in self):
            raise UserError("Choose a technician first.")
        return self._advance(["new"], "assigned")

    def action_diagnose(self):
        self._assignment()
        self._advance(["assigned", "waiting_parts"], "diagnosis")
        internal(self).write({"started_at": fields.Datetime.now()})
        self.unit_id._set_state("rework", "rework")
        return True

    def action_wait_parts(self):
        self._assignment()
        return self._advance(["diagnosis", "repairing"], "waiting_parts")

    def action_repair(self):
        self._assignment()
        return self._advance(["diagnosis", "waiting_parts"], "repairing")

    def action_ready(self):
        return ReworkService(self.env).ready(self)

    def action_scrap(self):
        require_role(self.env, "supervisor", "manager")
        if any(not r.corrective_action for r in self):
            raise UserError("Record the scrap disposition reason.")
        self._advance(["diagnosis", "waiting_parts", "repairing"], "scrapped")
        internal(self).write({"disposition": "scrap", "completed_at": fields.Datetime.now()})
        self.unit_id._set_state("scrapped", "hold", "Scrapped unfinished WIP; no finished receipt")
        return True

    def action_export(self):
        return export_xlsx(
            self,
            "Rework.xlsx",
            [
                "Rework",
                "Serial",
                "State",
                "Technician",
                "Root Cause",
                "Corrective Action",
                "Retest",
            ],
            [
                [
                    r.name,
                    r.unit_id.name,
                    r.state,
                    r.technician_id.name,
                    r.root_cause or "",
                    r.corrective_action or "",
                    r.retest_id.name or "",
                ]
                for r in self
            ],
        )
