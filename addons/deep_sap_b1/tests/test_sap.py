from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock, patch
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.deep_core.security import internal
from ..services.client import SAPError


@tagged("post_install", "-at_install")
class TestSAP(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.profile = cls.env["deep.sap.profile"].create(
            {
                "name": "Acceptance VPN source",
                "base_url": "https://sap.example.invalid:50000/b1s/v2",
                "sync_boms": False,
            }
        )
        cls.mapping = cls.env["deep.sap.warehouse.map"].create(
            {
                "profile_id": cls.profile.id,
                "sap_code": "01",
                "warehouse_id": cls.warehouse.id,
                "location_id": cls.warehouse.lot_stock_id.id,
            }
        )
        cls.env["deep.sap.uom.map"].create(
            {
                "profile_id": cls.profile.id,
                "sap_name": "Each",
                "uom_id": cls.env.ref("uom.product_uom_unit").id,
            }
        )

    def payload(self):
        return {
            "Items": [
                {
                    "ItemCode": "SAP-TEST-BUY",
                    "ItemName": "SAP acceptance component",
                    "InventoryItem": "tYES",
                    "InventoryUOM": "Each",
                    "PurchaseItem": "tYES",
                    "SalesItem": "tYES",
                    "ItemWarehouseInfoCollection": [
                        {"WarehouseCode": "01", "InStock": 5, "Committed": 2, "Ordered": 3}
                    ],
                }
            ],
            "BusinessPartners": [
                {
                    "CardCode": "SAP-V-TEST",
                    "CardName": "SAP acceptance supplier",
                    "CardType": "cSupplier",
                }
            ],
            "PurchaseOrders": [
                {
                    "DocEntry": 100,
                    "DocNum": 1000,
                    "CardCode": "SAP-V-TEST",
                    "DocDueDate": "2050-01-02",
                    "DocumentLines": [
                        {
                            "LineNum": 0,
                            "ItemCode": "SAP-TEST-BUY",
                            "WarehouseCode": "01",
                            "LineStatus": "bost_Open",
                            "RemainingOpenInventoryQuantity": 3,
                        }
                    ],
                }
            ],
            "Orders": [
                {
                    "DocEntry": 101,
                    "DocNum": 1001,
                    "CardCode": "SAP-C-TEST",
                    "DocDueDate": "2050-01-03",
                    "DocumentLines": [
                        {
                            "LineNum": 0,
                            "ItemCode": "SAP-TEST-BUY",
                            "WarehouseCode": "01",
                            "LineStatus": "bost_Open",
                            "RemainingOpenInventoryQuantity": 12,
                        }
                    ],
                }
            ],
        }

    def run_refresh(self, payload=None, failure=None):
        payload = payload or self.payload()
        client = MagicMock()
        client.__enter__.return_value = client
        client.collection.side_effect = failure or (
            lambda entity, params: deepcopy(payload[entity])
        )
        with patch(
            "odoo.addons.deep_sap_b1.models.profile.ServiceLayerClient.from_profile",
            return_value=client,
        ):
            action = self.profile.action_queue_sync()
            job = self.env["deep.sap.job"].browse(action["res_id"])
            job.action_run()
        return job

    def plan(self):
        product = (
            self.env["deep.sap.item"].search([("profile_id", "=", self.profile.id)]).product_id
        )
        return self.env["deep.mps.plan"].create(
            {
                "name": "SAP supply acceptance",
                "warehouse_id": self.warehouse.id,
                "start_date": "2050-01-01",
                "horizon": "weekly",
                "bucket_count": 1,
                "product_ids": [Command.set(product.ids)],
                "deep_sap_profile_id": self.profile.id,
            }
        )

    def test_repeat_refresh_is_idempotent_and_does_not_adjust_native_stock(self):
        first = self.run_refresh()
        self.assertEqual(first.state, "done")
        item = self.env["deep.sap.item"].search([("profile_id", "=", self.profile.id)])
        self.assertEqual(item.product_id.qty_available, 0)
        self.run_refresh()
        self.assertEqual(
            self.env["deep.sap.item"].search_count([("profile_id", "=", self.profile.id)]), 1
        )
        self.assertEqual(
            self.env["deep.sap.sales.line"].search_count([("profile_id", "=", self.profile.id)]), 1
        )
        demand = (
            self.env["deep.sap.sales.line"].search([("profile_id", "=", self.profile.id)]).demand_id
        )
        self.assertEqual(demand.quantity, 12)
        with self.assertRaises(AccessError):
            demand.write({"quantity": 13})
        with self.assertRaises(AccessError):
            self.env["deep.sap.stock"].search([("profile_id", "=", self.profile.id)]).with_context(
                _deep_capability=True
            ).write({"on_hand": 999})

    def test_sap_planning_uses_open_purchase_supply_and_preserves_scenario_source(self):
        self.run_refresh()
        plan = self.plan()
        product = plan.product_ids
        # A duplicate native supplier promise must not inflate the SAP-backed plan.
        move = self.env["stock.move"].create(
            {
                "description_picking_manual": "Duplicate supplier promise",
                "product_id": product.id,
                "product_uom_qty": 20,
                "product_uom": product.uom_id.id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
                "date": "2050-01-02 08:00:00",
            }
        )
        move._action_confirm()
        plan.action_calculate()
        self.assertEqual(plan.line_ids.beginning, 5)
        self.assertEqual(plan.line_ids.receipts, 3)
        self.assertEqual(plan.line_ids.planned, 4)
        scenario = self.env["deep.plan.scenario"].create(
            {"name": "SAP demand sensitivity", "base_plan_id": plan.id, "demand_factor": 2}
        )
        scenario.action_calculate()
        self.assertEqual(scenario.preview_plan_id.deep_sap_profile_id, self.profile)
        self.assertEqual(scenario.preview_plan_id.line_ids.planned, 16)
        self.assertEqual(plan.line_ids.planned, 4)

    def test_frozen_sales_change_rolls_back_entire_refresh(self):
        self.run_refresh()
        plan = self.plan()
        plan.action_calculate()
        plan.action_review()
        payload = self.payload()
        payload["Items"][0]["ItemWarehouseInfoCollection"][0]["InStock"] = 999
        payload["Orders"][0]["DocumentLines"][0]["RemainingOpenInventoryQuantity"] = 99
        job = self.run_refresh(payload)
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error_code, "FROZEN_DEMAND_CONFLICT")
        self.assertEqual(
            self.env["deep.sap.stock"].search([("profile_id", "=", self.profile.id)]).on_hand, 5
        )
        self.assertEqual(plan.source_demand_ids.quantity, 12)

    def test_incomplete_unit_mapping_rolls_back_new_master_records(self):
        payload = self.payload()
        bad = deepcopy(payload["Items"][0])
        bad.update(ItemCode="SAP-BAD-UNIT", InventoryUOM="Unmapped carton")
        payload["Items"].append(bad)
        job = self.run_refresh(payload)
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error_code, "ITEM_UNIT_MAPPING")
        self.assertFalse(self.env["deep.sap.item"].search([("profile_id", "=", self.profile.id)]))
        self.assertFalse(
            self.env["product.product"].search([("default_code", "=", "SAP-TEST-BUY")])
        )

    def test_stale_stock_blocks_planning_and_closed_orders_remove_only_draft_demand(self):
        self.run_refresh()
        plan = self.plan()
        internal(self.profile).write({"last_success": fields.Datetime.now() - timedelta(hours=2)})
        with self.assertRaises(UserError):
            plan.action_calculate()
        payload = self.payload()
        payload["Orders"] = []
        self.run_refresh(payload)
        self.assertFalse(
            self.env["deep.demand"].search(
                [("deep_sap_sales_line_id.profile_id", "=", self.profile.id)]
            )
        )
        self.assertFalse(
            self.env["deep.sap.sales.line"].search([("profile_id", "=", self.profile.id)]).current
        )

    def test_retry_history_and_pending_configuration_lock(self):
        action = self.profile.action_queue_sync()
        self.assertEqual(self.profile.action_queue_sync()["res_id"], action["res_id"])
        with self.assertRaises(UserError):
            self.mapping.write({"sap_code": "NEW"})
        with self.assertRaises(UserError):
            self.profile.write({"base_url": "https://changed.invalid/b1s/v2"})
        job = self.run_refresh(
            failure=SAPError("VPN_UNREACHABLE", "SAP could not be reached.", True)
        )
        self.assertEqual(job.state, "retry")
        self.assertEqual(job.attempts, 1)
        job.action_cancel()
        self.assertEqual(job.state, "cancel")

    def test_stock_reconciliation_requires_verified_unreserved_fresh_untracked_count(self):
        self.run_refresh()
        snapshot = self.env["deep.sap.stock"].search([("profile_id", "=", self.profile.id)])
        count = self.env["deep.sap.stock.count"].create(
            {"snapshot_id": snapshot.id, "reason": "Verified physical cutover count"}
        )
        with self.assertRaises(UserError):
            count.action_apply()
        count.verified = True
        count.action_apply()
        self.assertEqual(snapshot.product_id.qty_available, 5)
        move = self.env["stock.move"].create(
            {
                "description_picking_manual": "Active stock allocation",
                "product_id": snapshot.product_id.id,
                "product_uom_qty": 1,
                "product_uom": snapshot.product_id.uom_id.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        move._action_confirm()
        with self.assertRaises(UserError):
            count.action_apply()

    def test_company_rule_and_non_manager_connection_creation(self):
        company = self.env["res.company"].create({"name": "Unrelated SAP acceptance company"})
        user = self.env["res.users"].create(
            {
                "name": "SAP planner acceptance",
                "login": "sap-planner-acceptance",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "group_ids": [Command.set([self.env.ref("deep_core.group_planner").id])],
            }
        )
        other = (
            self.env["deep.sap.profile"].with_company(company).create({"name": "Other company SAP"})
        )
        self.assertFalse(
            self.env["deep.sap.profile"].with_user(user).search([("id", "=", other.id)])
        )
        with self.assertRaises(AccessError):
            self.env["deep.sap.profile"].with_user(user).create({"name": "Unauthorized endpoint"})

    def test_bom_import_prepares_inactive_revision_and_keeps_existing_orders(self):
        product = self.env.ref("deep_manufacturing_dashboard.demo_g7")
        bom = self.env.ref("deep_manufacturing_dashboard.demo_final_bom")
        self.profile.sync_boms = True
        payload = self.payload()
        for native in product | bom.bom_line_ids.product_id:
            payload["Items"].append(
                {
                    "ItemCode": native.default_code,
                    "ItemName": native.name,
                    "InventoryItem": "tYES",
                    "InventoryUOM": "Each",
                    "ManageSerialNumbers": "tYES" if native.tracking == "serial" else "tNO",
                    "ManageBatchNumbers": "tYES" if native.tracking == "lot" else "tNO",
                    "ItemWarehouseInfoCollection": [
                        {"WarehouseCode": "01", "InStock": 0, "Committed": 0, "Ordered": 0}
                    ],
                }
            )
        payload["ProductTrees"] = [
            {
                "TreeCode": product.default_code,
                "Quantity": bom.product_qty,
                "ProductTreeLines": [
                    {
                        "ItemCode": line.product_id.default_code,
                        "Quantity": line.product_qty,
                        "ItemType": "pit_Item",
                    }
                    for line in bom.bom_line_ids
                ],
            }
        ]
        job = self.run_refresh(payload)
        self.assertEqual(job.state, "done", job.message)
        snapshot = self.env["deep.sap.bom.snapshot"].search([("profile_id", "=", self.profile.id)])
        mo = self.env["mrp.production"].create(
            {
                "product_id": product.id,
                "product_qty": 1,
                "bom_id": bom.id,
                "picking_type_id": self.warehouse.manu_type_id.id,
            }
        )
        action = snapshot.action_prepare_change()
        change = self.env["deep.engineering.change"].browse(action["res_id"])
        self.assertFalse(change.proposed_bom_id.active)
        self.assertTrue(bom.active)
        self.assertEqual(len(change.proposed_bom_id.operation_ids), len(bom.operation_ids))
        self.assertTrue(
            all(
                not line.operation_id or line.operation_id.bom_id == change.proposed_bom_id
                for line in change.proposed_bom_id.bom_line_ids
            )
        )
        self.assertEqual(mo.bom_id, bom)
        self.assertEqual(snapshot.action_prepare_change()["res_id"], change.id)
