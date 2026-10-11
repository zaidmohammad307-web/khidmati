import base64
from datetime import timedelta

from odoo import Command, fields
from odoo.addons.deep_quality.services.quality import QualityService
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestManufacturingFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env.ref("deep_manufacturing_dashboard.demo_g7")
        cls.bom = cls.env.ref("deep_manufacturing_dashboard.demo_final_bom")
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        for p in cls.bom.bom_line_ids.product_id.filtered(lambda p: p.deep_make_buy == "make"):
            quant = (
                cls.env["stock.quant"]
                .with_context(inventory_mode=True)
                .create(
                    {
                        "product_id": p.id,
                        "location_id": cls.warehouse.lot_stock_id.id,
                        "inventory_quantity": 100,
                    }
                )
            )
            quant.action_apply_inventory()

    def make_order(self, quantity=2):
        mo = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "product_qty": quantity,
                "product_uom_id": self.product.uom_id.id,
                "bom_id": self.bom.id,
                "company_id": self.env.company.id,
                "picking_type_id": self.warehouse.manu_type_id.id,
            }
        )
        mo.action_confirm()
        return mo

    def issue(self, mo, quantity):
        wizard = self.env["deep.material.issue"].create({"production_id": mo.id})
        wizard._prepare()
        for planning_line in wizard.line_ids:
            planning_line.quantity = planning_line.raw_id.unit_factor * quantity
        result = wizard.action_issue()
        self.assertFalse(
            isinstance(result, dict) and result.get("res_model") == "stock.backorder.confirmation"
        )
        return wizard

    def serials(self, mo):
        for work in mo.workorder_ids.sorted("sequence"):
            if work.deep_checkpoint == "serialize":
                units = self.env["deep.production.unit"].browse(
                    work.action_deep_serialize(int(mo.product_qty), "serialize-test-key")
                )
                same = work.action_deep_serialize(int(mo.product_qty), "serialize-test-key")
                self.assertEqual(units.ids, same)
                work.button_finish()
                continue
            if work.deep_checkpoint == "test":
                return units, work
            work.button_finish()
        self.fail("No test checkpoint")

    def test_serial_failure_rework_retest_and_receipt(self):
        mo = self.make_order()
        self.issue(mo, 2)
        units, work = self.serials(mo)
        service = QualityService(self.env)
        with self.assertRaises(UserError):
            mo.button_mark_done()
        for index, u in enumerate(units):
            session = service.scan(u.name, work.id, "quality-scan-" + str(index))
            self.assertEqual(session, service.scan(u.name, work.id, "quality-scan-" + str(index)))
            answers = [
                {"point_id": p.id, "value": (15 if p.kind == "numeric" else index == 0)}
                for p in session.template_id.point_ids
                if p.mandatory
            ]
            service.submit(session, answers, "Initial inspection")
        bad = units.filtered(lambda u: u.state == "hold")
        good = units - bad
        self.assertEqual(len(bad), 1)
        self.assertEqual(len(good), 1)
        order = bad.rework_ids
        self.assertEqual(order.state, "new")
        order.technician_id = self.env.user
        order.action_assign()
        order.action_diagnose()
        order.action_repair()
        order.write(
            {
                "root_cause": "Sample assembly discrepancy",
                "corrective_action": "Adjusted and inspected sample assembly",
            }
        )
        order.action_ready()
        session = service.scan(bad.name, work.id, "quality-retest-key")
        self.assertEqual(order.state, "retesting")
        service.submit(
            session,
            [
                {"point_id": p.id, "value": 15 if p.kind == "numeric" else True}
                for p in session.template_id.point_ids
                if p.mandatory
            ],
            "Retest passed",
        )
        self.assertEqual(order.state, "closed")
        self.assertEqual(bad.state, "passed")
        self.assertEqual(len(bad.session_ids), 2)
        with self.assertRaises(AccessError):
            session.result_ids.write({"passed": False})
        consume = self.env["deep.material.issue"].create(
            {"production_id": mo.id, "mode": "consume"}
        )
        consume._prepare()
        for line in consume.line_ids:
            line.quantity = line.raw_id.unit_factor * 2
        consume.action_issue()
        units.action_prepare_selected()
        units.action_release()
        result = units.action_finish_selected()
        if isinstance(result, dict):
            self.fail("Unexpected completion wizard: " + str(result.get("res_model")))
        self.assertEqual(mo.state, "done")
        self.assertEqual(set(units.mapped("physical_zone")), {"finished"})
        finished = mo.move_finished_ids.filtered(lambda m: m.product_id == self.product)
        self.assertEqual(finished.state, "done")
        self.assertEqual(set(finished.move_line_ids.lot_id.ids), set(units.lot_id.ids))

    def test_partial_good_unit_release(self):
        mo = self.make_order()
        self.issue(mo, 2)
        units, work = self.serials(mo)
        service = QualityService(self.env)
        for index, u in enumerate(units):
            s = service.scan(u.name, work.id, "partial-scan-" + str(index))
            service.submit(
                s,
                [
                    {"point_id": p.id, "value": 15 if p.kind == "numeric" else index == 0}
                    for p in s.template_id.point_ids
                    if p.mandatory
                ],
                "Partial inspection",
            )
        good = units.filtered(lambda u: u.state == "passed")
        bad = units - good
        consume = self.env["deep.material.issue"].create(
            {"production_id": mo.id, "mode": "consume"}
        )
        consume._prepare()
        for line in consume.line_ids:
            line.quantity = line.raw_id.unit_factor
        consume.action_issue()
        good.action_prepare_selected()
        good.action_release()
        result = good.action_finish_selected()
        if isinstance(result, dict) and result.get("res_model") == "mrp.production.backorder":
            wizard = (
                self.env[result["res_model"]].with_context(**result.get("context", {})).create({})
            )
            wizard.action_backorder()
        self.assertEqual(mo.state, "done")
        self.assertNotEqual(bad.production_id, mo)
        self.assertEqual(bad.state, "hold")
        self.assertEqual(good.physical_zone, "finished")
        self.assertNotEqual(bad.physical_zone, "finished")

    def test_planned_60_actual_10(self):
        mo = self.make_order(60)
        self.issue(mo, 10)
        statuses = mo.deep_material_status()
        self.assertTrue(statuses)
        for row in statuses:
            self.assertEqual(row["planned"], 60)
            self.assertEqual(row["issued"], 10)
            self.assertEqual(row["consumed"], 0)
            self.assertEqual(row["remaining"], 50)

    def test_mps_forecast_and_idempotent_release(self):
        start = fields.Date.today() + timedelta(days=60)
        plan = self.env["deep.mps.plan"].create(
            {
                "name": "Test Plan",
                "warehouse_id": self.warehouse.id,
                "start_date": start,
                "bucket_count": 1,
                "product_ids": [Command.set(self.product.ids)],
            }
        )
        self.env["deep.demand"].create(
            [
                {
                    "name": "Firm",
                    "plan_id": plan.id,
                    "product_id": self.product.id,
                    "quantity": 60,
                    "required_date": start,
                    "category": "firm",
                },
                {
                    "name": "Forecast",
                    "plan_id": plan.id,
                    "product_id": self.product.id,
                    "quantity": 100,
                    "required_date": start,
                    "category": "forecast",
                    "confidence": 50,
                },
            ]
        )
        plan.action_calculate()
        self.assertEqual(plan.line_ids.total_demand, 100)
        self.assertEqual(plan.line_ids.weighted_demand, 60)
        self.assertTrue(plan.requirement_ids)
        plan.action_review()
        with self.assertRaises(UserError):
            plan.action_approve()
        plan.write(
            {
                "warnings_acknowledged": True,
                "approval_reason": "Reviewed demo supply and capacity exceptions",
            }
        )
        plan.action_approve()
        plan.action_firm()
        plan.action_release()
        count = len(plan.requirement_ids.production_id)
        plan.action_release()
        self.assertEqual(len(plan.requirement_ids.production_id), count)
        self.assertTrue(count)
        with self.assertRaises(UserError):
            plan.safety_stock = 20

    def test_mps_product_safety_stock_and_lot_sizing(self):
        uom = self.env.ref("uom.product_uom_unit")
        component = self.env["product.product"].create(
            {
                "name": "Lot Sized Propeller",
                "is_storable": True,
                "uom_id": uom.id,
                "deep_make_buy": "buy",
                "deep_lot_minimum": 50,
                "deep_lot_multiple": 25,
            }
        )
        finished = self.env["product.product"].create(
            {
                "name": "Lot Sized Drone",
                "is_storable": True,
                "uom_id": uom.id,
                "deep_make_buy": "make",
                "deep_safety_stock": 2,
                "deep_lot_multiple": 10,
            }
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [Command.create({"product_id": component.id, "product_qty": 2})],
            }
        )
        plan = self.env["deep.mps.plan"].create(
            {
                "name": "Lot Policy Plan",
                "warehouse_id": self.warehouse.id,
                "start_date": fields.Date.today() + timedelta(days=60),
                "bucket_count": 1,
                "safety_stock": 40,
            }
        )
        self.env["deep.demand"].create(
            {
                "name": "Firm",
                "plan_id": plan.id,
                "product_id": finished.id,
                "quantity": 21,
                "required_date": plan.start_date,
                "category": "firm",
            }
        )
        plan.action_calculate()
        # Item safety stock (2) overrides the plan default (40); 23 rounds up to a multiple of 10.
        self.assertEqual(plan.line_ids.planned, 30)
        self.assertEqual(plan.line_ids.balance, 9)
        buy = plan.requirement_ids.filtered(lambda row: row.product_id == component)
        # 60 propellers needed: above the 50 minimum, then rounded up to the 25-pack.
        self.assertEqual(buy.gross, 60)
        self.assertEqual(buy.net, 75)

    def test_import_dryrun_atomic_and_duplicates(self):
        header = "code,description,category,uom,make_buy,tracking,family,standard_cost,active\n"
        row = "TEST-IMPORT,Import Item,,Units,buy,none,,2,true\n"
        batch = self.env["deep.import.batch"].create(
            {
                "name": "Test Import",
                "kind": "items",
                "filename": "items.csv",
                "file": base64.b64encode((header + row).encode()),
            }
        )
        batch.action_validate()
        self.assertFalse(self.env["product.product"].search([("default_code", "=", "TEST-IMPORT")]))
        batch.action_approve()
        batch.action_apply()
        batch.action_apply()
        self.assertEqual(
            self.env["product.product"].search_count([("default_code", "=", "TEST-IMPORT")]), 1
        )
        duplicate = self.env["deep.import.batch"].create(
            {
                "name": "Duplicate",
                "kind": "items",
                "filename": "items.csv",
                "file": base64.b64encode((header + row).encode()),
            }
        )
        with self.assertRaises(UserError):
            duplicate.action_validate()
        invalid = self.env["deep.import.batch"].create(
            {
                "name": "Atomic",
                "kind": "items",
                "filename": "items.csv",
                "file": base64.b64encode(
                    (
                        header
                        + row.replace("TEST-IMPORT", "TEST-ROLLBACK")
                        + "BAD,Bad,,Unknown Unit,buy,none,,2,true\n"
                    ).encode()
                ),
            }
        )
        with self.assertRaises(UserError):
            invalid.action_validate()
        self.assertFalse(
            self.env["product.product"].search([("default_code", "=", "TEST-ROLLBACK")])
        )

    def test_operator_cannot_edit_bom_or_forge_serial(self):
        user = self.env["res.users"].create(
            {
                "name": "Test Operator",
                "login": "test.operator",
                "group_ids": [Command.set([self.env.ref("deep_core.group_operator").id])],
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
            }
        )
        with self.assertRaises(AccessError):
            self.bom.with_user(user).write({"deep_revision": "99"})
        with self.assertRaises(AccessError):
            self.env["deep.production.unit"].with_user(user).with_context(
                _deep_capability=True
            ).create({})

    def test_wrong_station_and_missing_mandatory_answer(self):
        mo = self.make_order(1)
        self.issue(mo, 1)
        units, work = self.serials(mo)
        service = QualityService(self.env)
        with self.assertRaises(UserError):
            service.scan(units.name, mo.workorder_ids[0].id, "wrong-station-key")
        session = service.scan(units.name, work.id, "mandatory-test-key")
        with self.assertRaises(UserError):
            service.submit(session, [], "")
        self.assertEqual(session.state, "draft")
        self.assertEqual(session, service.scan(units.name, work.id, "resume-draft-session"))
        with self.assertRaises(UserError):
            mo.workorder_ids.filtered(lambda w: w.deep_checkpoint == "release").button_finish()

    def test_multilevel_release_creates_real_subassembly_orders(self):
        start = fields.Date.today() + timedelta(days=90)
        plan = self.env["deep.mps.plan"].create(
            {
                "name": "Multilevel native MAKE test",
                "warehouse_id": self.warehouse.id,
                "start_date": start,
                "bucket_count": 1,
                "product_ids": [Command.set(self.product.ids)],
            }
        )
        self.env["deep.demand"].create(
            {
                "name": "Multilevel demand",
                "plan_id": plan.id,
                "product_id": self.product.id,
                "quantity": 1000,
                "required_date": start,
                "category": "firm",
            }
        )
        plan.action_calculate()
        make = plan.requirement_ids.filtered(lambda row: row.kind == "make" and row.net > 0)
        self.assertEqual(len(make), 4)
        self.assertTrue(plan.requirement_ids.filtered(lambda row: row.kind == "buy"))
        plan.action_review()
        plan.write({"warnings_acknowledged": True, "approval_reason": "Test reviewed exceptions"})
        plan.action_approve()
        plan.action_firm()
        plan.action_release()
        root = make.production_id.filtered(lambda mo: mo.product_id == self.product)
        children = make.production_id - root
        self.assertEqual(len(children), 3)
        self.assertTrue(all(mo.deep_parent_id == root for mo in children))
        self.assertTrue(all(mo.state == "draft" and mo.bom_id.operation_ids for mo in children))
        for child in children:
            child.action_confirm()
            self.assertEqual(len(child.workorder_ids), len(child.bom_id.operation_ids))
        with self.assertRaises(UserError):
            plan.source_demand_ids.write({"quantity": 2000})

    def test_company_record_rules(self):
        other = self.env["res.company"].create({"name": "Isolated test company"})
        family = self.env["deep.product.family"].create(
            {
                "name": "Other company family",
                "code": "ISOLATED",
                "company_id": other.id,
            }
        )
        user = self.env["res.users"].create(
            {
                "name": "Company scoped operator",
                "login": "company.scoped.operator",
                "group_ids": [Command.set([self.env.ref("deep_core.group_operator").id])],
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
            }
        )
        visible = self.env["deep.product.family"].with_user(user).search([("id", "=", family.id)])
        self.assertFalse(visible)

    def test_changed_draft_input_requires_recalculation(self):
        plan = self.env["deep.mps.plan"].create(
            {
                "name": "Stale input prevention",
                "warehouse_id": self.warehouse.id,
                "start_date": fields.Date.today() + timedelta(days=120),
                "bucket_count": 1,
                "product_ids": [Command.set(self.product.ids)],
            }
        )
        demand = self.env["deep.demand"].create(
            {
                "name": "Stale input demand",
                "plan_id": plan.id,
                "product_id": self.product.id,
                "quantity": 3,
                "required_date": plan.start_date,
                "category": "firm",
            }
        )
        plan.action_calculate()
        demand.quantity = 4
        self.assertFalse(plan.calculated_at)
        with self.assertRaises(UserError):
            plan.action_review()
        plan.action_calculate()
        plan.action_review()
        with self.assertRaises(UserError):
            demand.quantity = 5
        with self.assertRaises(UserError):
            plan.safety_stock = 1
