from datetime import timedelta
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.deep_quality.services.quality import QualityService
from odoo.addons.deep_manufacturing_dashboard.tests import test_workflow as original


@tagged("post_install", "-at_install")
class TestOperations(TransactionCase):
    make_order = original.TestManufacturingFlow.make_order
    issue = original.TestManufacturingFlow.issue
    serials = original.TestManufacturingFlow.serials

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env.ref("deep_manufacturing_dashboard.demo_g7")
        cls.bom = cls.env.ref("deep_manufacturing_dashboard.demo_final_bom")
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.department = cls.env["deep.production.department"].search(
            [("company_id", "=", cls.env.company.id), ("code", "=", "FA")], limit=1
        )
        cls.other_department = cls.env["deep.production.department"].search(
            [("company_id", "=", cls.env.company.id), ("code", "!=", "FA")], limit=1
        )
        for product in cls.bom.bom_line_ids.product_id.filtered(
            lambda product: product.deep_make_buy == "make"
        ):
            quant = (
                cls.env["stock.quant"]
                .with_context(inventory_mode=True)
                .create(
                    {
                        "product_id": product.id,
                        "location_id": cls.warehouse.lot_stock_id.id,
                        "inventory_quantity": 100,
                    }
                )
            )
            quant.action_apply_inventory()
        cls.team = cls.env["maintenance.team"].create(
            {"name": "Acceptance maintenance", "company_id": cls.env.company.id}
        )
        cls.equipment = cls.env["maintenance.equipment"].create(
            {
                "name": "Acceptance assembly fixture",
                "company_id": cls.env.company.id,
                "maintenance_team_id": cls.team.id,
            }
        )

    def make_kit(self, mo, capacity=2):
        kit = self.env["deep.material.kit"].create(
            {
                "production_id": mo.id,
                "department_id": self.department.id,
                "release_capacity": capacity,
            }
        )
        kit.action_fill_requirements()
        kit.action_request()
        kit.action_approve()
        return kit

    def passing_units(self, quantity=1):
        mo = self.make_order(quantity)
        self.issue(mo, quantity)
        units, work = self.serials(mo)
        service = QualityService(self.env)
        for unit in units:
            session = service.scan(unit.name, work.id, "acceptance-pass-" + str(unit.id))
            service.submit(
                session,
                [
                    {"point_id": point.id, "value": 15 if point.kind == "numeric" else True}
                    for point in session.template_id.point_ids
                    if point.mandatory
                ],
                "Verified acceptance unit",
            )
        return mo, units

    def receive_finished(self, mo, units):
        wizard = self.env["deep.material.issue"].create({"production_id": mo.id, "mode": "consume"})
        wizard._prepare()
        for line in wizard.line_ids:
            line.quantity = line.raw_id.unit_factor * len(units)
        wizard.action_issue()
        units.action_prepare_selected()
        units.action_release()
        result = units.action_finish_selected()
        self.assertFalse(isinstance(result, dict), str(result))
        # Three-step manufacturing receipts must reach Stock before customer delivery.
        for picking in mo.picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
            and picking.location_id == mo.location_dest_id
            and picking.location_dest_id == self.warehouse.lot_stock_id
        ):
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_context(skip_backorder=True).button_validate()
            self.assertEqual(picking.state, "done")

    def test_rack_capacity_issue_and_actual_return(self):
        mo = self.make_order(6)
        kit = self.make_kit(mo)
        for line in kit.line_ids:
            line.stage_qty = line.requested_qty
        kit.action_prepare()
        self.assertEqual(kit.state, "prepared")
        self.assertNotEqual(kit.rack_id, mo.location_src_id)
        line = kit.line_ids[0]
        self.assertEqual(line.staged_qty, 6)
        line.issue_qty = 3
        with self.assertRaises(UserError), self.cr.savepoint():
            kit.action_issue()
        line.issue_qty = 2
        kit.action_issue()
        self.assertEqual(line.issued_qty, 2)
        self.assertEqual(line.rack_qty, 4)
        returned = self.env["deep.kit.return"].create(
            {
                "kit_line_id": line.id,
                "quantity": 1,
                "reason": "Unused component returned to dedicated MO rack",
            }
        )
        returned.action_return()
        self.assertEqual(line.returned_qty, 1)
        self.assertEqual(line.rack_qty, 5)
        self.assertEqual(line.raw_id.state, "partially_available")
        self.assertEqual(line.raw_id.quantity, 1)
        self.assertNotEqual(mo.state, "done")
        self.assertTrue(
            self.env["deep.audit.event"].search_count(
                [("model", "=", kit._name), ("res_id", "=", kit.id), ("action", "=", "kit_return")]
            )
        )

    def test_repeated_component_issue_cannot_exceed_mo(self):
        mo = self.make_order(2)
        self.issue(mo, 2)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(mo, 1)
        for row in mo.deep_material_status():
            self.assertEqual(row["issued"], 2)

    def test_shift_approval_is_reported_actual_not_stock_receipt(self):
        mo = self.make_order(6)
        now = fields.Datetime.now()
        report = self.env["deep.shift.report"].create(
            {
                "name": "Morning shift",
                "department_id": self.department.id,
                "production_id": mo.id,
                "shift_start": now - timedelta(hours=8),
                "shift_end": now,
                "planned_qty": 6,
                "good_qty": 4,
                "rework_qty": 1,
                "scrap_qty": 1,
                "downtime_minutes": 30,
            }
        )
        report.action_submit()
        with self.assertRaises(AccessError), self.cr.savepoint():
            report.good_qty = 5
        report.action_approve()
        self.assertEqual(report.state, "approved")
        self.assertAlmostEqual(report.attainment, 400 / 6)
        self.assertEqual(report.labor_hours, 8)
        self.assertNotEqual(mo.state, "done")
        self.assertFalse(mo.move_finished_ids.filtered(lambda move: move.state == "done"))
        with self.assertRaises(AccessError), self.cr.savepoint():
            report.notes = "Alter approved history"

    def test_sent_handover_locks_receiver_and_contents(self):
        mo = self.make_order(3)
        receiver = self.env["res.users"].create(
            {
                "name": "Acceptance receiver",
                "login": "acceptance-receiver",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "group_ids": [Command.set([self.env.ref("deep_core.group_operator").id])],
            }
        )
        handover = self.env["deep.wip.handover"].create(
            {
                "name": "Department handover",
                "production_id": mo.id,
                "from_department_id": self.other_department.id,
                "to_department_id": self.department.id,
                "quantity": 3,
                "receiver_id": receiver.id,
            }
        )
        handover.action_send()
        with self.assertRaises(AccessError), self.cr.savepoint():
            handover.quantity = 2
        handover.with_user(receiver).action_receive()
        self.assertEqual(handover.state, "received")
        self.assertTrue(handover.received_at)

    def test_instruction_versions_and_acknowledgement_gate(self):
        mo = self.make_order(1)
        work = mo.workorder_ids.sorted("sequence")[0]
        work.operation_id.deep_instruction_required = True
        instruction = self.env["deep.work.instruction"].create(
            {
                "name": "Assembly SOP",
                "code": "ACCEPTANCE-SOP",
                "operation_ids": [Command.set(work.operation_id.ids)],
                "body": "<p>Inspect and secure this assembly.</p>",
                "approval_note": "Approved for acceptance",
            }
        )
        instruction.action_submit()
        instruction.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            work.button_start()
        service = self.env["deep.instruction.ack"]
        first = service.action_acknowledge(instruction.id, work.id)
        self.assertEqual(first, service.action_acknowledge(instruction.id, work.id))
        work.button_start()
        with self.assertRaises(AccessError), self.cr.savepoint():
            instruction.body = "changed after approval"
        action = instruction.action_revision()
        revision = self.env["deep.work.instruction"].browse(action["res_id"])
        revision.approval_note = "Reviewed improved procedure"
        revision.action_submit()
        revision.action_approve()
        self.assertEqual(instruction.state, "obsolete")
        self.assertEqual(revision.version, 2)
        self.assertFalse(service.search_count([("instruction_id", "=", revision.id)]))

    def test_downtime_blocks_starts_and_updates_native_calendar(self):
        mo = self.make_order(1)
        work = mo.workorder_ids.sorted("sequence")[0]
        now = fields.Datetime.now()
        event = self.env["deep.downtime.event"].create(
            {
                "name": "Fixture breakdown",
                "workcenter_id": work.workcenter_id.id,
                "workorder_id": work.id,
                "equipment_id": self.equipment.id,
                "maintenance_team_id": self.team.id,
                "reason_id": self.env["deep.downtime.reason"].search([], limit=1).id,
                "start": now - timedelta(minutes=15),
                "expected_end": now + timedelta(hours=1),
                "technician_id": self.env.uid,
            }
        )
        event.action_start()
        self.assertEqual(event.request_id.maintenance_type, "corrective")
        self.assertEqual(event.leave_id.resource_id, work.workcenter_id.resource_id)
        with self.assertRaises(UserError), self.cr.savepoint():
            work.button_start()
        extended = now + timedelta(hours=2)
        event.expected_end = extended
        self.assertEqual(event.leave_id.date_to, extended)
        event.write(
            {
                "root_cause": "Loose fixture fastener",
                "corrective_action": "Repaired and function checked",
            }
        )
        event.action_close()
        self.assertEqual(event.state, "closed")
        self.assertTrue(event.end)
        work.button_start()

    def test_preventive_plan_creates_native_dated_request(self):
        today = fields.Date.today()
        plan = self.env["deep.preventive.plan"].create(
            {
                "name": "Monthly fixture inspection",
                "equipment_id": self.equipment.id,
                "maintenance_team_id": self.team.id,
                "interval_days": 30,
                "next_date": today,
            }
        )
        plan.action_generate()
        self.assertEqual(plan.last_request_id.deep_due_date, today)
        self.assertEqual(plan.last_request_id.maintenance_type, "preventive")
        self.assertEqual(plan.next_date, today + timedelta(days=30))
        with self.assertRaises(AccessError), self.cr.savepoint():
            plan.last_request_id = False

    def test_scenario_recalculates_without_changing_base_or_releasing(self):
        start = fields.Date.today() + timedelta(days=80)
        base = self.env["deep.mps.plan"].create(
            {
                "name": "Acceptance base",
                "warehouse_id": self.warehouse.id,
                "start_date": start,
                "bucket_count": 1,
                "product_ids": [Command.set(self.product.ids)],
            }
        )
        self.env["deep.demand"].create(
            {
                "name": "Acceptance demand",
                "plan_id": base.id,
                "product_id": self.product.id,
                "quantity": 10,
                "category": "firm",
                "required_date": start,
            }
        )
        base.action_calculate()
        original_time = base.calculated_at
        original_qty = sum(base.line_ids.mapped("planned"))
        scenario = self.env["deep.plan.scenario"].create(
            {
                "name": "Demand doubles",
                "base_plan_id": base.id,
                "demand_factor": 2,
                "overtime_per_center": 4,
            }
        )
        scenario.action_calculate()
        self.assertEqual(base.calculated_at, original_time)
        self.assertEqual(sum(base.line_ids.mapped("planned")), original_qty)
        self.assertEqual(scenario.preview_plan_id.source_demand_ids.quantity, 20)
        self.assertEqual(scenario.preview_plan_id.state, "draft")
        with self.assertRaises(UserError), self.cr.savepoint():
            scenario.preview_plan_id.action_release()
        scenario.demand_factor = 1.5
        self.assertFalse(scenario.calculated_at)

    def test_engineering_approval_freezes_bom_and_preserves_existing_mo(self):
        mo = self.make_order(1)
        change = self.env["deep.engineering.change"].create(
            {
                "name": "Acceptance revision",
                "source_bom_id": self.bom.id,
                "revision": "ACCEPTANCE-R2",
                "reason": "Improve assembly procedure",
            }
        )
        change.action_clone()
        change.action_submit()
        change.action_approve()
        proposed = change.proposed_bom_id
        with self.assertRaises(AccessError), self.cr.savepoint():
            proposed.bom_line_ids[0].product_qty = 2
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["mrp.bom.line"].create(
                {
                    "bom_id": proposed.id,
                    "product_id": proposed.bom_line_ids[0].product_id.id,
                    "product_qty": 1,
                }
            )
        change.action_apply()
        self.assertTrue(proposed.active)
        self.assertFalse(self.bom.active)
        self.assertEqual(mo.bom_id, self.bom)
        self.assertEqual(change.state, "applied")

    def test_policy_sap_export_and_explicit_odoo_rule(self):
        product = self.bom.bom_line_ids.product_id[0]
        policy = self.env["deep.stock.policy"].create(
            {
                "name": "Acceptance reorder",
                "product_id": product.id,
                "warehouse_id": self.warehouse.id,
                "history_days": 7,
                "lead_days": 14,
                "coverage_days": 30,
            }
        )
        policy.action_calculate()
        self.assertEqual(policy.daily_mean, 0)
        self.assertEqual(policy.maximum_qty, 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            policy.action_apply_orderpoint()
        self.env.company.deep_procurement_mode = "odoo"
        policy.action_apply_orderpoint()
        self.assertTrue(policy.orderpoint_id)
        self.assertEqual(policy.orderpoint_id.trigger, "manual")
        policy.lead_days = 15
        self.assertFalse(policy.calculated_at)

    def test_blocking_capa_closure_required_for_release(self):
        mo, units = self.passing_units()
        case = self.env["deep.nonconformance"].create(
            {
                "name": "Acceptance containment",
                "production_id": mo.id,
                "unit_id": units.id,
                "description": "Additional release inspection",
                "blocking": True,
                "containment": "Unit isolated",
                "root_cause": "Fixture calibration review",
                "verification": "Effectiveness confirmed",
            }
        )
        units.action_prepare_selected()
        with self.assertRaises(UserError), self.cr.savepoint():
            units.action_release()
        case.action_contain()
        case.action_investigate()
        action = self.env["deep.capa.action"].create(
            {
                "name": "Calibrate fixture",
                "case_id": case.id,
                "completion_note": "Calibration verified against reference",
            }
        )
        case.action_actions()
        with self.assertRaises(UserError), self.cr.savepoint():
            case.action_verify()
        action.action_done()
        case.action_verify()
        case.action_close()
        self.assertEqual(case.state, "closed")
        units.action_release()
        self.assertEqual(units.state, "released")

    def test_contract_confirm_is_idempotent_and_delivery_uses_actual_stock(self):
        mo, units = self.passing_units()
        self.receive_finished(mo, units)
        customer = self.env["res.partner"].create({"name": "Acceptance customer"})
        contract = self.env["deep.customer.contract"].create(
            {
                "name": "Acceptance delivery",
                "reference": "ACCEPTANCE-CONTRACT",
                "customer_id": customer.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "First milestone",
                            "product_id": self.product.id,
                            "quantity": 1,
                            "due_date": fields.Date.today(),
                        }
                    )
                ],
            }
        )
        contract.action_confirm()
        demand = contract.line_ids.demand_id
        contract.action_confirm()
        self.assertEqual(contract.line_ids.demand_id, demand)
        with self.assertRaises(AccessError), self.cr.savepoint():
            demand.quantity = 2
        line = contract.line_ids
        action = line.action_prepare_delivery()
        picking = self.env["stock.picking"].browse(action["res_id"])
        move = picking.move_ids
        move.quantity = 1
        move.move_line_ids.lot_id = units.lot_id
        move.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(line.delivered_qty, 1)
        contract.action_close()
        self.assertEqual(contract.state, "closed")
        # A second generic shipment cannot bypass the contract by creating negative serial stock.
        duplicate = self.env["stock.move"].create(
            {
                "description_picking_manual": "Duplicate serial shipment",
                "product_id": self.product.id,
                "product_uom": self.product.uom_id.id,
                "product_uom_qty": 1,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": customer.property_stock_customer.id,
            }
        )
        duplicate._action_confirm()
        duplicate.quantity = 1
        duplicate.move_line_ids.lot_id = units.lot_id
        duplicate.picked = True
        with self.assertRaisesRegex(UserError, "Insufficient actual"), self.cr.savepoint():
            duplicate._action_done()

    def test_outbound_quality_case_blocks_shipment_after_receipt(self):
        mo, units = self.passing_units()
        self.receive_finished(mo, units)
        self.env["deep.nonconformance"].create(
            {
                "name": "Outbound containment",
                "unit_id": units.id,
                "production_id": mo.id,
                "description": "Shipping inspection hold",
                "blocking": True,
            }
        )
        customer = self.env["res.partner"].create({"name": "Outbound customer"})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": customer.property_stock_customer.id,
                "partner_id": customer.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "description_picking_manual": "Outbound inspection",
                "product_id": self.product.id,
                "product_uom": self.product.uom_id.id,
                "product_uom_qty": 1,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "picking_id": picking.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        move.quantity = 1
        move.move_line_ids.lot_id = units.lot_id
        move.picked = True
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.with_context(skip_backorder=True).button_validate()
        self.assertNotEqual(picking.state, "done")

    def test_workflow_results_cannot_be_forged_even_with_boolean_context(self):
        mo = self.make_order(1)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["deep.shift.report"].with_context(deep_internal=True).create(
                {
                    "name": "Forged",
                    "department_id": self.department.id,
                    "production_id": mo.id,
                    "shift_start": fields.Datetime.now(),
                    "shift_end": fields.Datetime.now() + timedelta(hours=1),
                    "approved_by": self.env.uid,
                }
            )
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["deep.plan.scenario"].create(
                {
                    "name": "Forged scenario",
                    "base_plan_id": self.env.ref("deep_manufacturing_dashboard.demo_plan").id,
                    "calculated_at": fields.Datetime.now(),
                }
            )
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["deep.stock.policy"].create(
                {
                    "name": "Forged proposal",
                    "product_id": self.bom.bom_line_ids.product_id[0].id,
                    "warehouse_id": self.warehouse.id,
                    "reorder_qty": 100,
                }
            )

    def test_control_tower_metrics_and_company_isolation(self):
        data = self.env["deep.control.tower"].metrics()
        self.assertEqual(data["company"], self.env.company.name)
        self.assertIn("kits", data)
        self.assertIn("alerts", data)
        company = self.env["res.company"].create({"name": "Isolated manufacturing company"})
        secret = self.env["deep.production.department"].create(
            {"name": "Other company department", "code": "SECRET", "company_id": company.id}
        )
        reader = self.env["res.users"].create(
            {
                "name": "Acceptance operator",
                "login": "acceptance-operator",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "group_ids": [Command.set([self.env.ref("deep_core.group_operator").id])],
            }
        )
        with self.assertRaises(AccessError), self.cr.savepoint():
            secret.with_user(reader).read(["name"])
        own = self.env["deep.control.tower"].with_user(reader).metrics()
        self.assertEqual(own["company"], self.env.company.name)
        self.assertFalse(any("Other company" in row["detail"] for row in own["alerts"]))

    def test_mo_wide_hold_blocks_each_unit_and_later_outbound_shipment(self):
        mo, units = self.passing_units(2)
        units.action_prepare_selected()
        case = self.env["deep.nonconformance"].create(
            {
                "name": "MO-wide inspection hold",
                "production_id": mo.id,
                "description": "Inspect both units after fixture calibration",
                "blocking": True,
                "containment": "Hold the entire MO",
                "root_cause": "Fixture calibration",
                "verification": "Both units inspected after correction",
            }
        )
        for unit in units:
            with self.assertRaisesRegex(UserError, "nonconformance"), self.cr.savepoint():
                unit.action_release()
        case.action_contain()
        case.action_investigate()
        action = self.env["deep.capa.action"].create(
            {
                "name": "Verify fixture",
                "case_id": case.id,
                "completion_note": "Reference calibration verified",
            }
        )
        case.action_actions()
        action.action_done()
        case.action_verify()
        case.action_close()
        self.receive_finished(mo, units)
        self.env["deep.nonconformance"].create(
            {
                "name": "MO-wide outbound hold",
                "production_id": mo.id,
                "description": "Shipment inspection",
                "blocking": True,
            }
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "description_picking_manual": "Two-unit held shipment",
                "product_id": self.product.id,
                "product_uom": self.product.uom_id.id,
                "product_uom_qty": 2,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "picking_id": picking.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        move._do_unreserve()
        move.move_line_ids.unlink()
        self.env["stock.move.line"].create(
            [
                {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "quantity": 1,
                    "lot_id": unit.lot_id.id,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                }
                for unit in units
            ]
        )
        move.picked = True
        with self.assertRaisesRegex(UserError, "quality case"), self.cr.savepoint():
            picking.with_context(skip_backorder=True).button_validate()
        self.assertNotEqual(picking.state, "done")
