"""Opt-in lab configuration; no approved production or shipment is invented."""

import os
from datetime import timedelta
from odoo import fields, Command


def post_init_hook(env):
    if os.environ.get("DEEP_DEMO_ENABLED", "1").lower() in ("0", "false", "no"):
        return
    if env["ir.config_parameter"].sudo().get_param("deep.demo.enabled", "True") == "False":
        return
    env = env(su=True)
    g7 = env.ref("deep_manufacturing_dashboard.demo_g7", raise_if_not_found=False)
    if not g7 or env["deep.production.department"].search_count(
        [("company_id", "=", env.company.id)]
    ):
        return
    for code, name in [
        ("FRAME", "Frame preparation"),
        ("MOTOR", "Motor assembly"),
        ("PCB", "Electronics assembly"),
        ("FA", "Final assembly"),
    ]:
        department = env["deep.production.department"].create(
            {
                "name": name,
                "code": code,
                "company_id": env.company.id,
                "supervisor_id": env.ref("base.user_admin").id,
            }
        )
        centers = env["mrp.workcenter"].search([("company_id", "=", env.company.id)])
        if code == "FA":
            centers = centers.filtered(
                lambda center: center.code
                and (
                    center.code.startswith("FA")
                    or (center.code.startswith("S") and center.code[1:].isdigit())
                )
            )
        else:
            centers = centers.filtered(
                lambda center: (center.code or "").startswith(
                    {"FRAME": "SA-1-", "MOTOR": "SA-2-", "PCB": "SA-3-"}[code]
                )
            )
        centers.deep_department_id = department
    for code, name, planned in [
        ("BREAKDOWN", "Equipment breakdown", False),
        ("MATERIAL", "Material waiting", False),
        ("SETUP", "Planned setup", True),
        ("PM", "Preventive maintenance", True),
    ]:
        env["deep.downtime.reason"].create(
            {"name": name, "code": code, "planned": planned, "company_id": env.company.id}
        )
    customer = env["res.partner"].create(
        {"name": "Demonstration project customer", "company_id": env.company.id}
    )
    env["deep.customer.contract"].create(
        {
            "name": "G7 pilot delivery",
            "reference": "DEMO-G7-DELIVERY",
            "customer_id": customer.id,
            "company_id": env.company.id,
            "notes": "Draft example: confirm only after approving your actual customer commitment.",
            "line_ids": [
                Command.create(
                    {
                        "name": "Pilot milestone",
                        "product_id": g7.id,
                        "quantity": 10,
                        "due_date": fields.Date.today() + timedelta(days=14),
                    }
                )
            ],
        }
    )
