"""Idempotent lab scenario. Creates native master data and audited inventory moves."""

import os
from datetime import timedelta

from odoo import Command, fields


def post_init_hook(env):
    if os.environ.get("DEEP_DEMO_ENABLED", "1").lower() in ("0", "false", "no"):
        return
    if env["ir.config_parameter"].sudo().get_param("deep.demo.enabled", "True") == "False":
        return
    seed_demo(env)


def seed_demo(env):
    env = env(su=True)
    company = env.company
    if env.ref("deep_manufacturing_dashboard.demo_g7", raise_if_not_found=False):
        return

    def register(name, record):
        env["ir.model.data"].create(
            {
                "module": "deep_manufacturing_dashboard",
                "name": name,
                "model": record._name,
                "res_id": record.id,
                "noupdate": True,
            }
        )
        return record

    family = register(
        "demo_family",
        env["deep.product.family"].create(
            {"name": "G7 Demo", "code": "G7", "company_id": company.id}
        ),
    )
    wh = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    wh.write({"manufacture_steps": "pbm_sam", "reception_steps": "three_steps"})
    for name in ("Quality Hold", "Rework"):
        env["stock.location"].create(
            {
                "name": name,
                "location_id": wh.view_location_id.id,
                "usage": "internal",
                "company_id": company.id,
            }
        )
    unit = env.ref("uom.product_uom_unit")

    def product(code, name, make=False, serial=False):
        return env["product.product"].create(
            {
                "name": name,
                "default_code": code,
                "type": "consu",
                "is_storable": True,
                "company_id": company.id,
                "uom_id": unit.id,
                "deep_make_buy": "make" if make else "buy",
                "tracking": "serial" if serial else "none",
            }
        )

    finished = register("demo_g7", product("DEMO-G7", "G7 Demo Drone", True, True))
    finished.write({"deep_family_id": family.id, "deep_qa_required": True})
    subs = [
        register("demo_sub_" + str(i), product(code, name, True))
        for i, (code, name) in enumerate(
            [
                ("SA-G7-FRAME", "G7 Frame Assembly"),
                ("SA-G7-MOTOR", "G7 Motor Set"),
                ("SA-G7-ELECTRONICS", "G7 Electronics Assembly"),
            ],
            1,
        )
    ]
    names = [
        "Frame material",
        "Frame spacer",
        "Frame fasteners",
        "Frame connector",
        "Frame finish",
        "Motor wire",
        "Motor magnet",
        "Motor bearing",
        "Motor shaft",
        "Motor fasteners",
        "PCB blank",
        "Electronic component A",
        "Electronic component B",
        "PCB connector",
        "Cable",
        "Camera sample",
        "Antenna sample",
        "Printed mount",
        "Final fasteners",
    ]
    raw = [product("DEMO-RM-" + str(i).zfill(2), name) for i, name in enumerate(names, 1)]
    vendor = env["res.partner"].create(
        {
            "name": "Demo Component Supplier",
            "ref": "DEMO-VENDOR",
            "supplier_rank": 1,
            "company_id": company.id,
        }
    )
    for i, p in enumerate(raw):
        env["product.supplierinfo"].create(
            {
                "product_tmpl_id": p.product_tmpl_id.id,
                "partner_id": vendor.id,
                "company_id": company.id,
                "price": 5 + i,
                "delay": 14 if i == 15 else 3,
            }
        )
        quant = (
            env["stock.quant"]
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": p.id,
                    "location_id": wh.lot_stock_id.id,
                    "inventory_quantity": 40 if i == 15 else 500,
                }
            )
        )
        quant.action_apply_inventory()

    def center(code, name, setup=0):
        c = env["mrp.workcenter"].create(
            {
                "name": name,
                "code": code,
                "company_id": company.id,
                "time_start": setup,
                "time_efficiency": 100,
            }
        )
        env["mrp.workcenter.capacity"].create(
            {"workcenter_id": c.id, "product_uom_id": unit.id, "capacity": 1}
        )
        return c

    groups = [
        ["CNC Cutting", "Deburring", "Frame Assembly", "Frame Inspection"],
        ["Winding", "Magnet Installation", "Mechanical Assembly", "Balancing", "Electrical Test"],
        ["SMD", "Reflow", "THT", "Programming", "Electrical Inspection"],
    ]
    boms = []
    for index, sub in enumerate(subs):
        bom = env["mrp.bom"].create(
            {
                "product_tmpl_id": sub.product_tmpl_id.id,
                "product_id": sub.id,
                "company_id": company.id,
                "product_qty": 1,
                "produce_delay": 2,
                "allow_operation_dependencies": True,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": p.id, "product_qty": 1, "product_uom_id": unit.id}
                    )
                    for p in raw[index * 5 : index * 5 + 5]
                ],
            }
        )
        previous = False
        for sequence, name in enumerate(groups[index], 1):
            c = center(
                f"SA-{index + 1}-{sequence:02}", name, 30 if index == 0 and sequence == 1 else 5
            )
            op = env["mrp.routing.workcenter"].create(
                {
                    "name": name,
                    "deep_code": c.code,
                    "bom_id": bom.id,
                    "workcenter_id": c.id,
                    "sequence": sequence,
                    "time_mode": "manual",
                    "time_cycle_manual": 12 if index == 0 and sequence == 1 else 5,
                    "deep_batch_size": 20,
                    "deep_operator_count": 2 if index == 0 and sequence == 1 else 1,
                    "blocked_by_operation_ids": [Command.link(previous.id)] if previous else [],
                }
            )
            previous = op
        boms.append(bom)
    final_bom = register(
        "demo_final_bom",
        env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_id": finished.id,
                "company_id": company.id,
                "product_qty": 1,
                "produce_delay": 1,
                "allow_operation_dependencies": True,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": p.id, "product_qty": 1, "product_uom_id": unit.id}
                    )
                    for p in subs + raw[15:]
                ],
            }
        ),
    )
    previous = False
    for i in range(1, 14):
        c = center(f"FA-S{i:02}", f"Final Assembly S{i:02}", 5)
        op = env["mrp.routing.workcenter"].create(
            {
                "name": f"S{i:02}",
                "deep_code": f"S{i:02}",
                "bom_id": final_bom.id,
                "workcenter_id": c.id,
                "sequence": i,
                "time_mode": "manual",
                "time_cycle_manual": 30 if i == 12 else 4,
                "deep_checkpoint": {9: "serialize", 12: "test", 13: "release"}.get(i, "normal"),
                "blocked_by_operation_ids": [Command.link(previous.id)] if previous else [],
            }
        )
        previous = op
    template = env["deep.quality.template"].create(
        {
            "name": "G7 Demo Functional Checklist",
            "company_id": company.id,
            "point_ids": [
                Command.create(
                    {
                        "name": "Visual inspection",
                        "code": "VISUAL",
                        "kind": "pass_fail",
                        "failure_code": "VISUAL",
                    }
                ),
                Command.create(
                    {
                        "name": "Numeric sample reading",
                        "code": "READING",
                        "kind": "numeric",
                        "minimum": 10,
                        "maximum": 20,
                        "unit": "sample units",
                        "failure_code": "READING",
                    }
                ),
                Command.create(
                    {
                        "name": "Inspection notes",
                        "code": "NOTES",
                        "kind": "text",
                        "mandatory": False,
                    }
                ),
            ],
        }
    )
    finished.deep_quality_template_id = template
    start = fields.Date.context_today(finished) + timedelta(days=21)
    plan = register(
        "demo_plan",
        env["deep.mps.plan"].create(
            {
                "name": "G7 Demo — 100 Units",
                "warehouse_id": wh.id,
                "start_date": start,
                "horizon": "weekly",
                "bucket_count": 1,
                "product_ids": [Command.set(finished.ids)],
            }
        ),
    )
    env["deep.demand"].create(
        {
            "name": "Demo Contract 100",
            "plan_id": plan.id,
            "product_id": finished.id,
            "required_date": start + timedelta(days=6),
            "quantity": 100,
            "category": "firm",
        }
    )
    # Existing operational order of 10 is separate from the future 100-unit contract.
    root = register(
        "demo_mo",
        env["mrp.production"].create(
            {
                "product_id": finished.id,
                "product_qty": 10,
                "product_uom_id": unit.id,
                "bom_id": final_bom.id,
                "company_id": company.id,
                "picking_type_id": wh.manu_type_id.id,
            }
        ),
    )
    root.action_confirm()
    for sub, bom in zip(subs, boms, strict=True):
        mo = env["mrp.production"].create(
            {
                "product_id": sub.id,
                "product_qty": 10,
                "product_uom_id": unit.id,
                "bom_id": bom.id,
                "company_id": company.id,
                "picking_type_id": wh.manu_type_id.id,
                "deep_parent_id": root.id,
            }
        )
        mo.action_confirm()
    plan.action_calculate()
    env["deep.material.risk"].action_refresh()
    env["ir.config_parameter"].set_param("deep.demo.seeded", "True")
