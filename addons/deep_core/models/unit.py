from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..security import internal, lock, require_internal, require_role
from ..services.export import export_xlsx


class Unit(models.Model):
    _name = "deep.production.unit"
    _description = "Serialized Production Genealogy"
    _check_company_auto = True
    _order = "id desc"
    name = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True)
    production_id = fields.Many2one(
        "mrp.production", required=True, check_company=True, ondelete="restrict", index=True
    )
    product_id = fields.Many2one(related="production_id.product_id", store=True)
    lot_id = fields.Many2one("stock.lot", required=True, check_company=True, ondelete="restrict")
    workorder_id = fields.Many2one("mrp.workorder", required=True, check_company=True)
    batch_id = fields.Many2one("deep.production.batch", check_company=True)
    operator_id = fields.Many2one("res.users", required=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)
    state = fields.Selection(
        [
            (v, v.replace("_", " ").title())
            for v in [
                "serialized",
                "testing",
                "hold",
                "rework",
                "retest",
                "passed",
                "released",
                "scrapped",
            ]
        ],
        default="serialized",
        required=True,
        readonly=True,
        index=True,
    )
    physical_zone = fields.Selection(
        [
            ("line", "Assembly Line"),
            ("hold", "Quality Hold"),
            ("rework", "Rework"),
            ("finished", "Finished Goods"),
        ],
        default="line",
        readonly=True,
    )
    release_at = fields.Datetime(readonly=True)
    print_count = fields.Integer(readonly=True)
    audit_ids = fields.One2many("deep.audit.event", "unit_id", readonly=True)
    qr_url = fields.Char(compute="_compute_qr")
    _unique = models.Constraint("UNIQUE(company_id, name)", "Serial identity already exists.")
    _lot = models.Constraint("UNIQUE(lot_id)", "This lot already identifies a unit.")

    @api.depends("name")
    def _compute_qr(self):
        for r in self:
            r.qr_url = (
                "/report/barcode/QR/" + quote(r.name or "", safe="") + "?width=240&height=240"
            )

    @api.model_create_multi
    def create(self, vals):
        require_internal(self.env)
        return super().create(vals)

    def write(self, vals):
        if set(vals) - {"batch_id"}:
            require_internal(self.env)
        return super().write(vals)

    def unlink(self):
        raise AccessError("Serialized genealogy cannot be deleted.")

    @api.constrains("production_id", "lot_id", "batch_id")
    def _identity(self):
        for r in self:
            if r.lot_id.product_id != r.product_id or r.lot_id.company_id != r.company_id:
                raise UserError("The lot must match this production product and company.")
            if r.batch_id and r.batch_id.production_id != r.production_id:
                raise UserError("The batch belongs to another MO.")

    def _set_state(self, state, zone="line", reason=""):
        for r in self:
            before = r.state
            vals = {"state": state, "physical_zone": zone}
            if state == "released":
                vals["release_at"] = fields.Datetime.now()
            internal(r.sudo()).write(vals)
            self.env["deep.audit.event"]._record(r, state, before, state, reason, r)

    def _check_release(self):
        for r in self:
            if r.state != "passed":
                raise UserError("A current passing quality test is required.")
            if any(
                w.state != "done"
                for w in r.production_id.workorder_ids
                if w.operation_id.deep_checkpoint != "release"
            ):
                raise UserError("Complete preceding operations before final release.")

    def action_release(self):
        require_role(self.env, "operator", "supervisor", "manager")
        lock(self)
        self._check_release()
        self._set_state("released", reason="Validated S13 release")
        return True

    def action_print(self):
        require_role(self.env, "operator", "qa", "supervisor", "manager")
        lock(self)
        for r in self:
            internal(r.sudo()).write({"print_count": r.print_count + 1})
            self.env["deep.audit.event"]._record(
                r, "qr_print" if r.print_count == 1 else "qr_reprint", unit=r
            )
        return self.env.ref("deep_core.action_unit_label").report_action(self)

    def action_export(self):
        return export_xlsx(
            self,
            "Serial_Genealogy.xlsx",
            [
                "Serial",
                "Product",
                "MO",
                "Batch",
                "Operator",
                "State",
                "Zone",
                "Event",
                "Time",
                "Reason",
            ],
            [
                [
                    r.name,
                    r.product_id.display_name,
                    r.production_id.name,
                    r.batch_id.name,
                    r.operator_id.name,
                    r.state,
                    r.physical_zone,
                    e.action,
                    str(e.at),
                    e.reason or "",
                ]
                for r in self
                for e in r.audit_ids
            ],
        )
