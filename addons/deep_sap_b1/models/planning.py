from odoo import api, fields, models
from odoo.addons.deep_core.security import require_internal
from odoo.exceptions import UserError


class Plan(models.Model):
    _inherit = "deep.mps.plan"
    deep_sap_profile_id = fields.Many2one(
        "deep.sap.profile",
        check_company=True,
        help="Optional SAP stock and open PO planning source. Stock uses on-hand: SAP commitments are shown separately because imported sales demand is netted by MPS.",
    )

    def _deep_available_stock(self, product):
        if not self.deep_sap_profile_id:
            return super()._deep_available_stock(product)
        profile = self.deep_sap_profile_id
        profile._check_fresh()
        rows = self.env["deep.sap.stock"].search(
            [
                ("profile_id", "=", profile.id),
                ("product_id", "=", product.id),
                ("mapping_id.warehouse_id", "=", self.warehouse_id.id),
            ]
        )
        mappings = profile.warehouse_ids.filtered(
            lambda mapping: mapping.warehouse_id == self.warehouse_id
        )
        if (
            not mappings
            or set(rows.mapping_id.ids) != set(mappings.ids)
            or any(
                not row.observed_at
                or (fields.Datetime.now() - row.observed_at).total_seconds()
                > profile.max_age_minutes * 60
                for row in rows
            )
        ):
            raise UserError(
                "SAP stock is missing or stale for "
                + product.display_name
                + " in this plan warehouse."
            )
        return sum(rows.mapped("on_hand"))

    def _deep_incoming_supply(self, products):
        result = super()._deep_incoming_supply(products)
        if not self.deep_sap_profile_id:
            return result
        profile = self.deep_sap_profile_id
        profile._check_fresh()
        # Preserve native manufacturing receipts; exclude native purchasing to avoid counting SAP POs twice.
        result = self._deep_native_supply(products, source_usages=["production"])
        rows = self.env["deep.sap.purchase.line"].search(
            [
                ("profile_id", "=", profile.id),
                ("current", "=", True),
                ("mapping_id.warehouse_id", "=", self.warehouse_id.id),
                ("product_id", "in", products.ids),
            ]
        )
        for row in rows:
            result.setdefault(row.product_id.id, []).append([row.due_date, row.quantity])
        return result


class Demand(models.Model):
    _inherit = "deep.demand"
    deep_sap_sales_line_id = fields.Many2one("deep.sap.sales.line", check_company=True, copy=False)

    @api.model_create_multi
    def create(self, values):
        if any(value.get("deep_sap_sales_line_id") for value in values):
            require_internal(self.env)
        return super().create(values)

    def write(self, values):
        if "deep_sap_sales_line_id" in values or (
            self.deep_sap_sales_line_id and set(values) - {"released_plan_id"}
        ):
            require_internal(self.env)
        return super().write(values)

    def unlink(self):
        if self.deep_sap_sales_line_id:
            require_internal(self.env)
        return super().unlink()


class Scenario(models.Model):
    _inherit = "deep.plan.scenario"

    def _preview_source_values(self):
        return {
            **super()._preview_source_values(),
            "deep_sap_profile_id": self.base_plan_id.deep_sap_profile_id.id,
        }


class Company(models.Model):
    _inherit = "res.company"
    deep_sap_profile_id = fields.Many2one("deep.sap.profile", check_company=True)


class Tower(models.AbstractModel):
    _inherit = "deep.control.tower"

    @api.model
    def metrics(self):
        data = super().metrics()
        profiles = self.env["deep.sap.profile"].search(
            [("company_id", "=", self.env.company.id), ("active", "=", True)]
        )
        data["sap"] = [
            {
                "id": profile.id,
                "name": profile.name,
                "state": profile.connection_state,
                "last_success": str(profile.last_success or ""),
                "automatic": profile.automatic_sync,
                "message": profile.status_message or "Not configured",
            }
            for profile in profiles
        ]
        for profile in profiles:
            stale = (
                not profile.last_success
                or (fields.Datetime.now() - profile.last_success).total_seconds()
                > profile.max_age_minutes * 60
            )
            if stale or profile.connection_state == "error":
                data["alerts"].insert(
                    0,
                    {
                        "key": "sap:" + str(profile.id),
                        "model": "deep.sap.profile",
                        "id": profile.id,
                        "title": "SAP synchronization needs attention",
                        "detail": profile.name
                        + " · "
                        + (
                            profile.status_message
                            or "Complete the connection settings and first refresh."
                        ),
                        "severity": "critical"
                        if profile.connection_state == "error"
                        else "attention",
                    },
                )
        return data
