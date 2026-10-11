import base64
import hashlib
import json

from odoo import api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_internal, require_role
from odoo.addons.deep_core.services.export import export_xlsx
from odoo.exceptions import UserError

from ..services.importer import HEADERS, ImportService


class Batch(models.Model):
    _name = "deep.import.batch"
    _description = "Approved Atomic Master Data Import"
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    kind = fields.Selection([(k, k.replace("_", " ").title()) for k in HEADERS], required=True)
    file = fields.Binary(required=True, attachment=True)
    filename = fields.Char(required=True)
    mode = fields.Selection(
        [("create", "Create Only"), ("upsert", "Create / Update")], default="create", required=True
    )
    state = fields.Selection(
        [(k, k.title()) for k in ["draft", "validated", "approved", "applied"]],
        default="draft",
        readonly=True,
    )
    digest = fields.Char(readonly=True)
    report = fields.Text(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    applied_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals):
        if any(v.get("state", "draft") != "draft" for v in vals):
            raise UserError("New imports start in Draft.")
        return super().create(vals)

    def write(self, vals):
        if set(vals) & {"state", "digest", "report", "approved_by", "applied_at"}:
            require_internal(self.env)
        if set(vals) & {"file", "filename", "kind", "mode", "company_id"} and any(
            b.state != "draft" for b in self
        ):
            raise UserError("Validated content is frozen; create a new import batch.")
        return super().write(vals)

    def _content(self):
        payload = base64.b64decode(self.file, validate=True)
        if len(payload) > 5 * 1024 * 1024:
            raise UserError("Maximum upload size is 5 MB.")
        return payload, hashlib.sha256(payload).hexdigest()

    def action_template(self):
        self.ensure_one()
        return export_xlsx(self, self.kind + "_template.xlsx", HEADERS[self.kind], [])

    def action_validate(self):
        require_role(self.env, "planner", "manager")
        for b in self:
            lock(b)
            if b.state != "draft":
                raise UserError("Validate a new draft import.")
            payload, digest = b._content()
            service = ImportService(self.env, b)
            rows = service.parse(payload)

            class DryRunRollback(Exception):
                pass

            counts = {}
            try:
                with self.env.cr.savepoint():
                    counts = service.apply(rows)
                    raise DryRunRollback()
            except DryRunRollback:
                pass
            internal(b).write(
                {
                    "state": "validated",
                    "digest": digest,
                    "report": json.dumps(
                        {**counts, "status": "Dry run: no business records committed"}, indent=2
                    ),
                }
            )
        return True

    def action_approve(self):
        require_role(self.env, "manager")
        for b in self:
            lock(b)
            if b.state != "validated":
                raise UserError("Validate before manager approval.")
            internal(b).write({"state": "approved", "approved_by": self.env.uid})
        return True

    def action_apply(self):
        require_role(self.env, "manager")
        for b in self:
            lock(b)
            if b.state == "applied":
                continue
            if b.state != "approved":
                raise UserError("Manager approval is required.")
            payload, digest = b._content()
            if digest != b.digest:
                raise UserError("Approved file content changed.")
            service = ImportService(self.env, b)
            counts = service.apply(service.parse(payload))
            internal(b).write(
                {
                    "state": "applied",
                    "applied_at": fields.Datetime.now(),
                    "report": json.dumps({**counts, "status": "Committed atomically"}, indent=2),
                }
            )
            self.env["deep.audit.event"]._record(b, "import_applied", reason=digest)
        return True

    def unlink(self):
        if any(b.state != "draft" for b in self):
            raise UserError("Validated import history is permanent.")
        return super().unlink()
