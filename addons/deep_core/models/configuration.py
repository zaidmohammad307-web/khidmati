import re
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from ..security import require_role, require_internal


class Family(models.Model):
    _name = "deep.product.family"
    _description = "Product Family Serial Configuration"
    _check_company_auto = True
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    sequence_id = fields.Many2one("ir.sequence", readonly=True, check_company=True)
    _code_unique = models.Constraint("UNIQUE(company_id, code)", "Family code already exists.")

    @api.model_create_multi
    def create(self, vals):
        require_role(self.env, "planner", "manager")
        if any(not re.fullmatch(r"[A-Z0-9_-]+", v.get("code", "")) for v in vals):
            raise ValidationError("Use uppercase letters, numbers, underscores and hyphens.")
        records = super().create(vals)
        for r in records:
            r.sequence_id = (
                self.env["ir.sequence"]
                .sudo()
                .create(
                    {
                        "name": r.name,
                        "code": f"deep.serial.{r.company_id.id}.{r.id}",
                        "prefix": r.code + "-%(year)s-",
                        "padding": 6,
                        "use_date_range": True,
                        "company_id": r.company_id.id,
                    }
                )
            )
        return records

    def write(self, vals):
        if set(vals) & {"code", "company_id"}:
            raise ValidationError("Create a new family to change its immutable serial identity.")
        return super().write(vals)


class Product(models.Model):
    _inherit = "product.template"
    deep_family_id = fields.Many2one("deep.product.family", check_company=True)
    deep_make_buy = fields.Selection([("make", "Make"), ("buy", "Buy")], default="buy")
    deep_qa_required = fields.Boolean("Mandatory serialized final release")

    def write(self, vals):
        if any(key.startswith("deep_") for key in vals):
            require_role(self.env, "planner", "manager")
        return super().write(vals)


class Company(models.Model):
    _inherit = "res.company"

    def write(self, vals):
        if "deep_procurement_mode" in vals:
            require_role(self.env, "manager")
        return super().write(vals)

    deep_procurement_mode = fields.Selection(
        [("sap", "Export suggestions to SAP B1"), ("odoo", "Native Odoo RFQs")],
        default="sap",
        required=True,
    )


class Operation(models.Model):
    _inherit = "mrp.routing.workcenter"
    deep_code = fields.Char(index=True)
    deep_checkpoint = fields.Selection(
        [
            ("normal", "Normal"),
            ("serialize", "Serial / S9"),
            ("test", "Scan / S12"),
            ("release", "Final release / S13"),
        ],
        default="normal",
        required=True,
    )
    deep_batch_size = fields.Float(
        help="0 uses one native MO batch. Positive values repeat setup per batch."
    )
    deep_setup = fields.Float(default=-1, help="-1 uses work-center setup minutes.")
    deep_cleanup = fields.Float(default=-1)
    deep_operator_count = fields.Integer(default=1)
    deep_yield = fields.Float(default=100)
    deep_minimum_batch = fields.Float()
    deep_maximum_batch = fields.Float()
    _valid = models.Constraint(
        "CHECK(deep_batch_size >= 0 AND deep_operator_count > 0 AND deep_yield > 0 AND deep_yield <= 100)",
        "Invalid operation settings.",
    )

    @api.model_create_multi
    def create(self, vals):
        require_role(self.env, "planner", "manager")
        return super().create(vals)

    def write(self, vals):
        require_role(self.env, "planner", "manager")
        return super().write(vals)

    def unlink(self):
        require_role(self.env, "planner", "manager")
        return super().unlink()


class Bom(models.Model):
    _inherit = "mrp.bom"
    deep_revision = fields.Char(default="1", required=True)
    deep_effective_date = fields.Date()

    @api.model_create_multi
    def create(self, vals):
        require_role(self.env, "planner", "manager")
        return super().create(vals)

    def write(self, vals):
        require_role(self.env, "planner", "manager")
        return super().write(vals)

    def unlink(self):
        require_role(self.env, "manager")
        return super().unlink()


class BomLine(models.Model):
    _inherit = "mrp.bom.line"
    deep_scrap_pct = fields.Float()
    _scrap = models.Constraint(
        "CHECK(deep_scrap_pct >= 0 AND deep_scrap_pct < 100)", "Scrap must be below 100%."
    )

    @api.model_create_multi
    def create(self, vals):
        require_role(self.env, "planner", "manager")
        return super().create(vals)

    def write(self, vals):
        require_role(self.env, "planner", "manager")
        return super().write(vals)

    def unlink(self):
        require_role(self.env, "planner", "manager")
        return super().unlink()


class ServiceResult(models.AbstractModel):
    _name = "deep.service.result"
    _description = "Immutable Service Owned Result"

    @api.model_create_multi
    def create(self, vals):
        require_internal(self.env)
        return super().create(vals)

    def write(self, vals):
        require_internal(self.env)
        return super().write(vals)

    def unlink(self):
        require_internal(self.env)
        return super().unlink()


class Vendor(models.Model):
    _inherit = "res.partner"
    deep_default_lead_days = fields.Integer("Default supplier lead days")
    _lead_days = models.Constraint(
        "CHECK(deep_default_lead_days>=0)", "Lead days cannot be negative."
    )
