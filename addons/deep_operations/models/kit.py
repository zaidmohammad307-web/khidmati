from odoo import Command, api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_internal, require_role
from odoo.exceptions import AccessError, UserError


class Kit(models.Model):
    _name = "deep.material.kit"
    _description = "MO Department Material Kit / Staging Rack"
    _inherit = "deep.workflow.document"
    _check_company_auto = True
    name = fields.Char(default="New", readonly=True, copy=False, required=True)
    production_id = fields.Many2one("mrp.production", required=True, check_company=True, index=True)
    department_id = fields.Many2one("deep.production.department", required=True, check_company=True)
    state = fields.Selection(
        [
            (key, key.title())
            for key in ["draft", "requested", "approved", "prepared", "issued", "cancel"]
        ],
        default="draft",
    )
    rack_id = fields.Many2one("stock.location", readonly=True, check_company=True)
    release_capacity = fields.Float(
        required=True, default=1, help="Maximum MO-equivalent quantity in one department issue."
    )
    required_date = fields.Date(default=fields.Date.context_today)
    reason = fields.Text()
    line_ids = fields.One2many("deep.material.kit.line", "kit_id", copy=False)
    picking_ids = fields.One2many("stock.picking", "deep_kit_id", readonly=True)
    _unique = models.Constraint(
        "UNIQUE(production_id,department_id)", "One kit per MO and department."
    )
    _capacity = models.Constraint(
        "CHECK(release_capacity>0)", "Department release capacity must be positive."
    )
    _protected_fields = {"state", "name", "rack_id"}
    _frozen_states = ("cancel",)

    @api.model_create_multi
    def create(self, values):
        for value in values:
            if value.get("rack_id"):
                require_internal(self.env)
            value["name"] = self.env["ir.sequence"].sudo().next_by_code("deep.material.kit")
        return super().create(values)

    def write(self, values):
        if set(values) & {"production_id", "department_id", "line_ids"} and any(
            record.state != "draft" for record in self
        ):
            raise AccessError("Requested kit requirements are frozen.")
        if "release_capacity" in values:
            require_role(self.env, "supervisor", "manager")
        return super().write(values)

    def action_fill_requirements(self):
        require_role(self.env, "planner", "supervisor", "manager")
        for record in self:
            if record.state != "draft" or record.production_id.state in ("draft", "done", "cancel"):
                raise UserError("Fill a draft kit for a confirmed active MO.")
            raw = record.production_id.move_raw_ids.filtered(
                lambda move: move.state not in ("done", "cancel")
            )
            assigned = raw.filtered(
                lambda move: (
                    move.bom_line_id.operation_id.workcenter_id.deep_department_id
                    == record.department_id
                )
            )
            # Unassigned BOM components can be kitted by the chosen department; never silently omit them.
            other = self.search(
                [
                    ("production_id", "=", record.production_id.id),
                    ("id", "!=", record.id),
                    ("state", "!=", "cancel"),
                ]
            ).line_ids.raw_id
            selected = (
                assigned
                | raw.filtered(
                    lambda move: not move.bom_line_id.operation_id.workcenter_id.deep_department_id
                )
            ) - other
            if not selected:
                raise UserError("No MO components are assigned to this department.")
            record.line_ids = [Command.clear()] + [
                Command.create({"raw_id": move.id, "requested_qty": move.product_uom_qty})
                for move in selected
            ]
        return True

    def action_request(self):
        require_role(self.env, "planner", "supervisor", "manager")
        if any(not record.line_ids for record in self):
            raise UserError("Fill the kit requirements first.")
        return self._transition(["draft"], "requested")

    def action_approve(self):
        require_role(self.env, "supervisor", "manager")
        return self._transition(
            ["requested"], "approved", self[:1].reason or "Department staging approved"
        )

    def _rack(self):
        self.ensure_one()
        if not self.rack_id:
            warehouse = self.production_id.picking_type_id.warehouse_id
            rack = (
                self.env["stock.location"]
                .sudo()
                .create(
                    {
                        "name": self.name,
                        "location_id": warehouse.view_location_id.id,
                        "usage": "internal",
                        "company_id": self.company_id.id,
                    }
                )
            )
            internal(self).write({"rack_id": rack.id})
        return self.rack_id

    def action_prepare(self):
        require_role(self.env, "warehouse", "manager")
        self.ensure_one()
        lock(self)
        if self.state not in ("approved", "prepared"):
            raise UserError("Approve the kit before staging actual material.")
        from ..services.transfers import TransferService

        selected = self.line_ids.filtered(lambda line: line.stage_qty > 0)
        if not selected:
            raise UserError(
                "Enter actual quantities to stage; zero never means the planned quantity."
            )
        TransferService(self.env).stage(self, selected)
        internal(self).write({"state": "prepared"})
        return True

    def action_issue(self):
        require_role(self.env, "warehouse", "manager")
        self.ensure_one()
        lock(self)
        if self.state != "prepared":
            raise UserError("Prepare the rack before issuing material.")
        from ..services.transfers import TransferService

        selected = self.line_ids.filtered(lambda line: line.issue_qty > 0)
        if not selected:
            raise UserError("Enter actual department issue quantities.")
        TransferService(self.env).issue(self, selected)
        if all(line.issued_qty - line.returned_qty >= line.requested_qty for line in self.line_ids):
            internal(self).write({"state": "issued"})
        return True

    def action_cancel(self):
        require_role(self.env, "supervisor", "manager")
        if any(
            record.picking_ids.filtered(lambda picking: picking.state == "done") for record in self
        ):
            raise UserError(
                "Return actual stock through native moves before cancelling a used kit."
            )
        return self._transition(["draft", "requested", "approved"], "cancel", self[:1].reason or "")


class KitLine(models.Model):
    _name = "deep.material.kit.line"
    _description = "Requested / Staged / Issued Component"
    _check_company_auto = True
    kit_id = fields.Many2one("deep.material.kit", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="kit_id.company_id", store=True)
    raw_id = fields.Many2one("stock.move", required=True, check_company=True)
    product_id = fields.Many2one(related="raw_id.product_id", store=True)
    uom_id = fields.Many2one(related="raw_id.product_uom")
    requested_qty = fields.Float(required=True)
    stage_qty = fields.Float(help="Actual additional quantity to stage now.")
    issue_qty = fields.Float(help="Actual additional quantity to issue now.")
    lot_id = fields.Many2one("stock.lot", check_company=True)
    move_ids = fields.One2many("stock.move", "deep_kit_line_id", readonly=True)
    staged_qty = fields.Float(compute="_movement")
    issued_qty = fields.Float(compute="_movement")
    returned_qty = fields.Float(compute="_movement")
    rack_qty = fields.Float(compute="_movement")
    shortage = fields.Float(compute="_movement")
    _positive = models.Constraint(
        "CHECK(requested_qty>0 AND stage_qty>=0 AND issue_qty>=0)", "Invalid kit quantities."
    )
    _unique = models.Constraint("UNIQUE(kit_id,raw_id)", "Duplicate component in this kit.")

    @api.constrains("kit_id", "raw_id", "requested_qty", "lot_id")
    def _identity(self):
        for line in self:
            if (
                line.raw_id.raw_material_production_id != line.kit_id.production_id
                or line.requested_qty > line.raw_id.product_uom_qty
            ):
                raise UserError("Kit quantities must belong to the selected MO requirement.")
            if line.lot_id and line.lot_id.product_id != line.product_id:
                raise UserError("Component lot does not match the product.")

    @api.model_create_multi
    def create(self, values):
        kits = self.env["deep.material.kit"].browse([value["kit_id"] for value in values])
        if any(kit.state != "draft" for kit in kits):
            raise AccessError("Requested kit requirements are frozen.")
        return super().create(values)

    def write(self, values):
        if set(values) & {"kit_id", "raw_id", "requested_qty"} and any(
            line.kit_id.state != "draft" for line in self
        ):
            raise AccessError("Requested kit requirements are frozen.")
        if set(values) & {"stage_qty", "issue_qty", "lot_id"}:
            require_role(self.env, "warehouse", "manager")
        return super().write(values)

    def unlink(self):
        if any(line.kit_id.state != "draft" for line in self):
            raise AccessError("Requested kit requirements are permanent.")
        return super().unlink()

    def action_return(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.kit.return",
            "view_mode": "form",
            "target": "new",
            "context": {"default_kit_line_id": self.id},
        }

    @api.depends(
        "move_ids.state",
        "move_ids.quantity",
        "move_ids.origin_returned_move_id",
        "move_ids.location_id",
        "move_ids.location_dest_id",
        "requested_qty",
        "kit_id.rack_id",
    )
    def _movement(self):
        for line in self:
            done = line.move_ids.filtered(lambda move: move.state == "done")

            def amount(move):
                return move.product_uom._compute_quantity(move.quantity, line.uom_id)

            line.staged_qty = sum(
                amount(move)
                for move in done
                if move.location_dest_id == line.kit_id.rack_id and not move.origin_returned_move_id
            )
            line.issued_qty = sum(
                amount(move) for move in done if move.location_id == line.kit_id.rack_id
            )
            line.returned_qty = sum(amount(move) for move in done if move.origin_returned_move_id)
            line.rack_qty = max(0, line.staged_qty + line.returned_qty - line.issued_qty)
            line.shortage = max(0, line.requested_qty - line.staged_qty)
