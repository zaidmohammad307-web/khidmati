from odoo import api, fields, models, Command
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import internal, require_role, lock


class WarehouseMap(models.Model):
    _name = "deep.sap.warehouse.map"
    _description = "SAP Warehouse to Odoo Warehouse / Count Location"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="profile_id.company_id", store=True)
    sap_code = fields.Char(required=True)
    warehouse_id = fields.Many2one("stock.warehouse", required=True, check_company=True)
    location_id = fields.Many2one("stock.location", required=True, check_company=True)
    _unique = models.Constraint("UNIQUE(profile_id,sap_code)", "SAP warehouse is already mapped.")
    _location = models.Constraint(
        "UNIQUE(profile_id,location_id)",
        "Use distinct native count locations for distinct SAP warehouses.",
    )

    @api.constrains("warehouse_id", "location_id")
    def _location_check(self):
        for record in self:
            if record.location_id.usage != "internal" or record.location_id not in self.env[
                "stock.location"
            ].search([("id", "child_of", record.warehouse_id.view_location_id.id)]):
                raise UserError("Map an internal location inside the selected native warehouse.")

    def write(self, values):
        self.profile_id._check_mapping_edit()
        return super().write(values)

    @api.model_create_multi
    def create(self, values):
        self.env["deep.sap.profile"].browse(
            [value["profile_id"] for value in values]
        )._check_mapping_edit()
        return super().create(values)

    def unlink(self):
        self.profile_id._check_mapping_edit()
        return super().unlink()


class UomMap(models.Model):
    _name = "deep.sap.uom.map"
    _description = "SAP Inventory Unit to Native Unit Mapping"
    profile_id = fields.Many2one("deep.sap.profile", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="profile_id.company_id", store=True)
    sap_name = fields.Char(required=True)
    uom_id = fields.Many2one("uom.uom", required=True)
    quantity_factor = fields.Float(required=True, default=1)
    _unique = models.Constraint(
        "UNIQUE(profile_id,sap_name)", "SAP inventory UOM is already mapped."
    )
    _factor = models.Constraint("CHECK(quantity_factor>0)", "Unit factor must be positive.")

    def write(self, values):
        self.profile_id._check_mapping_edit()
        if self.env["deep.sap.item"].search_count(
            [("profile_id", "in", self.profile_id.ids), ("sap_uom", "in", self.mapped("sap_name"))]
        ):
            raise UserError(
                "Bound item unit mappings are frozen; resolve conversion changes as an explicit migration."
            )
        return super().write(values)

    @api.model_create_multi
    def create(self, values):
        self.env["deep.sap.profile"].browse(
            [value["profile_id"] for value in values]
        )._check_mapping_edit()
        return super().create(values)

    def unlink(self):
        self.profile_id._check_mapping_edit()
        if self.env["deep.sap.item"].search_count(
            [("profile_id", "in", self.profile_id.ids), ("sap_uom", "in", self.mapped("sap_name"))]
        ):
            raise UserError("A bound SAP inventory UOM cannot be deleted.")
        return super().unlink()


class Profile(models.Model):
    _inherit = "deep.sap.profile"

    def _check_mapping_edit(self):
        require_role(self.env, "manager")
        lock(self)
        if (
            self.env["deep.sap.job"]
            .sudo()
            .search_count(
                [("profile_id", "in", self.ids), ("state", "in", ["queued", "running", "retry"])]
            )
        ):
            raise UserError("Finish or cancel the pending job before changing mappings.")


class Item(models.Model):
    _name = "deep.sap.item"
    _description = "SAP Item Identity / Native Product Binding"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    sap_code = fields.Char(required=True, index=True)
    sap_uom = fields.Char(required=True)
    quantity_factor = fields.Float(required=True, default=1)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    last_seen = fields.Datetime()
    _unique = models.Constraint("UNIQUE(profile_id,sap_code)", "SAP item is already bound.")
    _product = models.Constraint(
        "UNIQUE(profile_id,product_id)", "A native product has one SAP identity per connection."
    )


class Partner(models.Model):
    _name = "deep.sap.partner"
    _description = "SAP Business Partner Binding"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    sap_code = fields.Char(required=True)
    partner_id = fields.Many2one("res.partner", required=True, check_company=True)
    kind = fields.Char()
    _unique = models.Constraint(
        "UNIQUE(profile_id,sap_code)", "SAP business partner is already bound."
    )


class Stock(models.Model):
    _name = "deep.sap.stock"
    _description = "Timestamped SAP Warehouse Stock Snapshot"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    item_id = fields.Many2one("deep.sap.item", required=True, check_company=True)
    product_id = fields.Many2one(related="item_id.product_id", store=True)
    mapping_id = fields.Many2one("deep.sap.warehouse.map", required=True, check_company=True)
    on_hand = fields.Float()
    committed = fields.Float()
    ordered = fields.Float()
    observed_at = fields.Datetime()
    job_id = fields.Many2one("deep.sap.job", check_company=True)
    _unique = models.Constraint("UNIQUE(item_id,mapping_id)", "Duplicate SAP warehouse snapshot.")

    def action_reconcile_stock(self):
        require_role(self.env, "manager")
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.sap.stock.count",
            "view_mode": "form",
            "target": "new",
            "context": {"default_snapshot_id": self.id},
        }


class Supply(models.Model):
    _name = "deep.sap.purchase.line"
    _description = "SAP Open Purchase Supply / External Logistics"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    doc_entry = fields.Integer(required=True)
    doc_number = fields.Char()
    line_number = fields.Integer(required=True)
    vendor_code = fields.Char()
    item_id = fields.Many2one("deep.sap.item", required=True, check_company=True)
    product_id = fields.Many2one(related="item_id.product_id", store=True)
    mapping_id = fields.Many2one("deep.sap.warehouse.map", required=True, check_company=True)
    quantity = fields.Float()
    due_date = fields.Date(required=True)
    observed_at = fields.Datetime()
    current = fields.Boolean(default=True)
    _unique = models.Constraint(
        "UNIQUE(profile_id,doc_entry,line_number)", "SAP PO line is already imported."
    )


class Sales(models.Model):
    _name = "deep.sap.sales.line"
    _description = "SAP Customer Order / Firm MPS Demand Binding"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    doc_entry = fields.Integer(required=True)
    doc_number = fields.Char()
    line_number = fields.Integer(required=True)
    customer_code = fields.Char()
    item_id = fields.Many2one("deep.sap.item", required=True, check_company=True)
    product_id = fields.Many2one(related="item_id.product_id", store=True)
    quantity = fields.Float()
    due_date = fields.Date(required=True)
    demand_id = fields.Many2one("deep.demand", check_company=True)
    observed_at = fields.Datetime()
    current = fields.Boolean(default=True)
    _unique = models.Constraint(
        "UNIQUE(profile_id,doc_entry,line_number)", "SAP sales line is already imported."
    )


class BomSnapshot(models.Model):
    _name = "deep.sap.bom.snapshot"
    _description = "SAP BOM Snapshot / Reviewed Engineering Import"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    item_id = fields.Many2one("deep.sap.item", required=True, check_company=True)
    product_id = fields.Many2one(related="item_id.product_id", store=True)
    quantity = fields.Float()
    components = fields.Json()
    fingerprint = fields.Char()
    observed_at = fields.Datetime()
    change_id = fields.Many2one("deep.engineering.change", check_company=True)
    _unique = models.Constraint(
        "UNIQUE(profile_id,item_id)", "SAP BOM snapshot is already imported."
    )

    def action_prepare_change(self):
        require_role(self.env, "planner", "manager")
        self.ensure_one()
        lock(self)
        self.profile_id._check_fresh()
        if (
            not self.observed_at
            or (fields.Datetime.now() - self.observed_at).total_seconds()
            > self.profile_id.max_age_minutes * 60
        ):
            raise UserError("Refresh this BOM snapshot before preparing its engineering change.")
        if self.change_id:
            change = self.change_id
        else:
            bom = (
                self.env["mrp.bom"]
                ._bom_find(self.product_id, company_id=self.company_id.id, bom_type="normal")
                .get(self.product_id)
            )
            if not bom:
                raise UserError(
                    "Configure the native product BOM and routing first; SAP BOM snapshots do not invent work stations."
                )
            revision = "SAP-" + self.fingerprint[:12]
            change = self.env["deep.engineering.change"].create(
                {
                    "name": "SAP BOM review / " + self.item_id.sap_code,
                    "company_id": self.company_id.id,
                    "source_bom_id": bom.id,
                    "revision": revision,
                    "reason": "Reviewed SAP snapshot " + self.fingerprint,
                    "impact": "Review quantities, component operations, revision effectivity and routing before approval.",
                }
            )
            change.action_clone()
            operations = {
                line.product_id.id: line.operation_id.id
                for line in change.proposed_bom_id.bom_line_ids
            }
            change.proposed_bom_id.write(
                {
                    "product_qty": self.quantity,
                    "bom_line_ids": [Command.clear()]
                    + [
                        Command.create(
                            {
                                "product_id": row["product_id"],
                                "product_qty": row["quantity"],
                                "product_uom_id": self.env["product.product"]
                                .browse(row["product_id"])
                                .uom_id.id,
                                "operation_id": operations.get(row["product_id"], False),
                            }
                        )
                        for row in self.components
                    ],
                }
            )
            internal(self.sudo()).write({"change_id": change.id})
            self.env["deep.audit.event"]._record(self, "sap_bom_change_prepared", reason=revision)
        return {
            "type": "ir.actions.act_window",
            "res_model": change._name,
            "res_id": change.id,
            "view_mode": "form",
        }


class StockCount(models.TransientModel):
    _name = "deep.sap.stock.count"
    _description = "Approved Native Count from Verified SAP Stock"
    snapshot_id = fields.Many2one("deep.sap.stock", required=True, readonly=True)
    product_id = fields.Many2one(related="snapshot_id.product_id")
    location_id = fields.Many2one(related="snapshot_id.mapping_id.location_id")
    sap_quantity = fields.Float(related="snapshot_id.on_hand")
    observed_at = fields.Datetime(related="snapshot_id.observed_at")
    reason = fields.Text(required=True)
    verified = fields.Boolean(
        "I verified the physical count, unit mapping and cutover; SAP stock was not counted twice"
    )

    def action_apply(self):
        require_role(self.env, "manager")
        self.ensure_one()
        snapshot = self.snapshot_id
        lock(snapshot.profile_id)
        lock(snapshot)
        snapshot.profile_id._check_fresh()
        if (
            not snapshot.observed_at
            or (fields.Datetime.now() - snapshot.observed_at).total_seconds()
            > snapshot.profile_id.max_age_minutes * 60
        ):
            raise UserError(
                "This item snapshot is missing or stale. Refresh it before reconciling stock."
            )
        if not self.verified or not self.reason:
            raise UserError("Verify the physical count and give its reconciliation reason.")
        if snapshot.product_id.tracking != "none" or snapshot.on_hand < 0:
            raise UserError(
                "Aggregate SAP stock cannot reconcile tracked or negative quantities; use an approved native lot/serial count."
            )
        if self.env["stock.move"].search_count(
            [
                ("company_id", "=", snapshot.company_id.id),
                ("product_id", "=", snapshot.product_id.id),
                ("state", "not in", ["draft", "done", "cancel"]),
                "|",
                ("location_id", "child_of", self.location_id.id),
                ("location_dest_id", "child_of", self.location_id.id),
            ],
            limit=1,
        ):
            raise UserError(
                "Resolve active native stock moves for this item/location before reconciling its count."
            )
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product_id.id),
                ("location_id", "=", self.location_id.id),
                ("company_id", "=", snapshot.company_id.id),
            ]
        )
        lock(quants)
        if (
            any(
                quant.reserved_quantity or quant.owner_id or quant.package_id or quant.lot_id
                for quant in quants
            )
            or len(quants) > 1
        ):
            raise UserError(
                "Resolve reservations, owners or packages before applying this aggregate count."
            )
        quant = quants or self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product_id.id,
                "location_id": self.location_id.id,
                "company_id": snapshot.company_id.id,
            }
        )
        quant.with_context(inventory_mode=True).inventory_quantity = snapshot.on_hand
        quant.action_apply_inventory()
        self.env["deep.audit.event"]._record(
            snapshot,
            "sap_stock_reconciled",
            reason=self.reason + " / count " + str(snapshot.on_hand),
        )
        return {"type": "ir.actions.act_window_close"}
