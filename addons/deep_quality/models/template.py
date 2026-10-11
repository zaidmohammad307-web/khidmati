from odoo import api, fields, models
from odoo.exceptions import UserError


class Template(models.Model):
    _name = "deep.quality.template"
    _description = "Versioned Product Quality Template"
    _check_company_auto = True
    name = fields.Char(required=True)
    version = fields.Integer(default=1, required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    point_ids = fields.One2many("deep.quality.point", "template_id", copy=True)
    active = fields.Boolean(default=True)
    _version = models.Constraint("CHECK(version>0)", "Version must be positive.")

    def _unused(self):
        if (
            self.env["deep.quality.session"]
            .sudo()
            .search_count([("template_id", "in", self.ids)], limit=1)
        ):
            raise UserError("This version has test history. Duplicate the template to revise it.")

    def write(self, vals):
        if set(vals) - {"active"}:
            self._unused()
        return super().write(vals)

    def unlink(self):
        self._unused()
        return super().unlink()

    def copy(self, default=None):
        self.ensure_one()
        return super().copy({**(default or {}), "version": self.version + 1})


class Point(models.Model):
    _name = "deep.quality.point"
    _description = "Typed Quality Test Point"
    _order = "sequence,id"
    template_id = fields.Many2one("deep.quality.template", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="template_id.company_id", store=True)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    instruction = fields.Text()
    kind = fields.Selection(
        [
            (s, s.replace("_", " ").title())
            for s in ["pass_fail", "numeric", "boolean", "text", "selection"]
        ],
        default="pass_fail",
        required=True,
    )
    mandatory = fields.Boolean(default=True)
    minimum = fields.Float()
    maximum = fields.Float()
    unit = fields.Char()
    expected_boolean = fields.Boolean(default=True)
    options = fields.Text(help="One allowed selection per line.")
    expected_text = fields.Char()
    failure_code = fields.Char()
    _code = models.Constraint("UNIQUE(template_id,code)", "Duplicate test code in this version.")
    _bounds = models.Constraint(
        "CHECK(kind!='numeric' OR maximum>=minimum)", "Invalid numeric limits."
    )

    @api.model_create_multi
    def create(self, vals):
        self.env["deep.quality.template"].browse([v["template_id"] for v in vals])._unused()
        return super().create(vals)

    def write(self, vals):
        self.template_id._unused()
        if vals.get("template_id"):
            self.env["deep.quality.template"].browse(vals["template_id"])._unused()
        return super().write(vals)

    def unlink(self):
        self.template_id._unused()
        return super().unlink()


class Product(models.Model):
    _inherit = "product.template"
    deep_quality_template_id = fields.Many2one("deep.quality.template", check_company=True)
