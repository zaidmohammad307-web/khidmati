from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.addons.deep_core.security import require_internal
from odoo.addons.deep_core.services.export import export_xlsx
from ..services.quality import QualityService


class Scan(models.Model):
    _name = "deep.scan.event"
    _inherit = "deep.service.result"
    _description = "Server Recorded Scan"
    company_id = fields.Many2one("res.company", required=True)
    unit_id = fields.Many2one(
        "deep.production.unit", required=True, ondelete="restrict", index=True
    )
    workorder_id = fields.Many2one("mrp.workorder", required=True)
    operator_id = fields.Many2one("res.users", required=True)
    at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    request_key = fields.Char(required=True)
    _key = models.Constraint(
        "UNIQUE(company_id,operator_id,request_key)", "Scan request already exists."
    )

    def write(self, vals):
        raise AccessError("Scan history is immutable.")

    def unlink(self):
        raise AccessError("Scan history is permanent.")


class Session(models.Model):
    _name = "deep.quality.session"
    _description = "Serial Quality Session"
    _check_company_auto = True
    _order = "id desc"
    name = fields.Char(related="unit_id.name")
    company_id = fields.Many2one("res.company", required=True)
    unit_id = fields.Many2one(
        "deep.production.unit", required=True, check_company=True, ondelete="restrict", index=True
    )
    workorder_id = fields.Many2one("mrp.workorder", required=True, check_company=True)
    scan_id = fields.Many2one("deep.scan.event", required=True, ondelete="restrict")
    template_id = fields.Many2one("deep.quality.template", required=True, check_company=True)
    version = fields.Integer(required=True)
    tester_id = fields.Many2one("res.users", required=True)
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    ended_at = fields.Datetime(index=True)
    state = fields.Selection(
        [("draft", "In Test"), ("done", "Locked")], default="draft", required=True, readonly=True
    )
    outcome = fields.Selection(
        [("pass", "PASS"), ("fail", "FAIL"), ("hold", "HOLD")], readonly=True
    )
    notes = fields.Text()
    failure_category = fields.Char()
    result_ids = fields.One2many("deep.quality.result", "session_id", readonly=True)
    attachment_ids = fields.Many2many("ir.attachment")
    _scan = models.Constraint("UNIQUE(scan_id)", "A scan starts one test session only.")

    @api.model_create_multi
    def create(self, vals):
        require_internal(self.env)
        return super().create(vals)

    def write(self, vals):
        if set(vals) - {"notes", "attachment_ids", "failure_category"}:
            require_internal(self.env)
        if any(s.state == "done" for s in self):
            raise AccessError("Historical results are locked. Create a retest.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Quality history is permanent.")

    def init(self):
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS deep_quality_session_unit_history ON deep_quality_session (unit_id, id DESC)"
        )
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS deep_quality_session_company_outcome ON deep_quality_session (company_id, outcome, ended_at) WHERE state='done'"
        )

    def _on_started(self):
        return True

    def _on_failure(self):
        return True

    def _on_pass(self):
        return True

    @api.model
    def action_scan(self, serial, workorder_id, request_key):
        s = QualityService(self.env).scan(serial, workorder_id, request_key)
        return {
            "id": s.id,
            "serial": s.unit_id.name,
            "state": s.state,
            "outcome": s.outcome,
            "template": s.template_id.name,
            "version": s.version,
            "points": [
                {
                    "id": p.id,
                    "name": p.name,
                    "kind": p.kind,
                    "instruction": p.instruction or "",
                    "mandatory": p.mandatory,
                    "minimum": p.minimum,
                    "maximum": p.maximum,
                    "unit": p.unit or "",
                    "options": (p.options or "").splitlines(),
                }
                for p in s.template_id.point_ids
            ],
        }

    def action_submit(self, answers, notes="", hold=False):
        self.ensure_one()
        return QualityService(self.env).submit(self, answers, notes, hold)

    def action_export(self):
        return export_xlsx(
            self,
            "Quality.xlsx",
            ["Serial", "Version", "Tester", "Time", "Point", "Type", "Value", "Passed", "Failure"],
            [
                [
                    s.unit_id.name,
                    s.version,
                    s.tester_id.name,
                    str(s.ended_at),
                    r.point_id.name,
                    r.kind,
                    str(
                        r.numeric_value
                        if r.kind == "numeric"
                        else r.boolean_value
                        if r.kind in ("boolean", "pass_fail")
                        else r.text_value
                    ),
                    r.passed,
                    r.failure_code or "",
                ]
                for s in self
                for r in s.result_ids
            ],
        )


class Result(models.Model):
    _name = "deep.quality.result"
    _inherit = "deep.service.result"
    _description = "Immutable Typed Quality Result"
    session_id = fields.Many2one(
        "deep.quality.session", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(related="session_id.company_id", store=True)
    point_id = fields.Many2one("deep.quality.point", required=True, ondelete="restrict")
    kind = fields.Selection(related="point_id.kind", store=True)
    numeric_value = fields.Float()
    boolean_value = fields.Boolean()
    text_value = fields.Text()
    passed = fields.Boolean(required=True)
    failure_code = fields.Char()
    _unique = models.Constraint(
        "UNIQUE(session_id,point_id)", "A point can be answered once per session."
    )

    def write(self, vals):
        raise AccessError("Test results are immutable.")

    def unlink(self):
        raise AccessError("Test results are permanent.")
