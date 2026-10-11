from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.deep_core.security import require_role
from odoo.addons.deep_core.services.export import export_xlsx


class Tower(models.AbstractModel):
    _name = "deep.control.tower"
    _description = "Company-scoped Live Operations Control Tower"

    @api.model
    def metrics(self):
        require_role(
            self.env,
            "planner",
            "operator",
            "warehouse",
            "supervisor",
            "qa",
            "technician",
            "procurement",
            "manager",
        )
        domain = [("company_id", "=", self.env.company.id)]
        today = fields.Date.context_today(self)
        alerts = []

        def records(model, extra=(), order="id desc", limit=200):
            return self.env[model].search(domain + list(extra), order=order, limit=limit)

        def count(model, extra=()):
            return self.env[model].search_count(domain + list(extra))

        def alert(record, title, detail, severity="attention"):
            alerts.append(
                {
                    "key": record._name + ":" + str(record.id),
                    "model": record._name,
                    "id": record.id,
                    "title": title,
                    "detail": detail,
                    "severity": severity,
                }
            )

        active = [("state", "not in", ["draft", "done", "cancel"])]
        orders = records("mrp.production", active, "deep_priority,date_start,id", 100)
        kits = records(
            "deep.material.kit", [("state", "not in", ["issued", "cancel"])], "required_date,id"
        )
        kit_rows = []
        for kit in kits:
            missing = sum(1 for line in kit.line_ids if line.shortage > 0)
            kit_rows.append(
                {
                    "id": kit.id,
                    "name": kit.name,
                    "mo": kit.production_id.name,
                    "department": kit.department_id.name,
                    "rack": kit.rack_id.display_name or "Awaiting preparation",
                    "capacity": kit.release_capacity,
                    "missing": missing,
                    "state": kit.state,
                    "date": str(kit.required_date or ""),
                }
            )
            if (
                kit.state in ("requested", "approved", "prepared")
                and missing
                and kit.required_date
                and kit.required_date <= today
            ):
                alert(
                    kit,
                    "Material rack needs attention",
                    kit.production_id.name
                    + " · "
                    + kit.department_id.name
                    + " · "
                    + str(missing)
                    + " unstaged components",
                )
        breakdowns = records("deep.downtime.event", [("state", "=", "open")], "start,id")
        for event in breakdowns:
            alert(
                event,
                "Center stopped" if event.block_starts else "Recorded downtime",
                event.workcenter_id.name + " · " + event.reason_id.name,
                "critical" if event.block_starts else "attention",
            )
        cases = records("deep.nonconformance", [("state", "!=", "closed")], "due_date,id")
        for case in cases:
            if case.blocking or case.due_date < today:
                alert(
                    case,
                    "Quality release blocked" if case.blocking else "Quality case overdue",
                    case.name + " · " + case.owner_id.name,
                    "critical" if case.blocking else "attention",
                )
        capa = records(
            "deep.capa.action", [("state", "!=", "done"), ("due_date", "<", today)], "due_date,id"
        )
        for action in capa:
            alert(action, "Corrective action overdue", action.name + " · " + action.owner_id.name)
        preventive = records(
            "deep.preventive.plan",
            [("active", "=", True), ("next_date", "<=", today)],
            "next_date,id",
        )
        for plan in preventive:
            alert(plan, "Preventive maintenance due", plan.name + " · " + str(plan.next_date))
        handovers = records("deep.wip.handover", [("state", "=", "sent")], "sent_at,id")
        for handover in handovers:
            alert(
                handover,
                "Awaiting receiver acknowledgement",
                handover.name + " · " + handover.receiver_id.name,
            )
        instructions = records(
            "deep.work.instruction",
            [
                ("state", "=", "approved"),
                ("valid_until", "!=", False),
                ("valid_until", "<=", today + timedelta(days=7)),
            ],
            "valid_until,id",
        )
        for instruction in instructions:
            alert(
                instruction,
                "Instruction expired"
                if instruction.valid_until < today
                else "Instruction expires soon",
                instruction.code
                + " v"
                + str(instruction.version)
                + " · "
                + str(instruction.valid_until),
            )
        milestones = records(
            "deep.contract.milestone", [("contract_id.state", "=", "confirmed")], "due_date,id"
        )
        for line in milestones:
            if line.remaining_qty > 0 and line.due_date <= today:
                alert(
                    line,
                    "Customer delivery overdue"
                    if line.due_date < today
                    else "Customer delivery due today",
                    line.contract_id.reference
                    + " · "
                    + str(line.remaining_qty)
                    + " units remaining",
                    "critical" if line.due_date < today else "attention",
                )
        for order in orders:
            if order.deep_promise_date and order.deep_promise_date < today:
                alert(
                    order,
                    "MO promise date overdue",
                    order.name + " · " + order.product_id.display_name,
                )
        shift_domain = [
            ("state", "=", "approved"),
            ("shift_start", ">=", str(today - timedelta(days=6))),
        ]
        report_values = self.env["deep.shift.report"]._read_group(
            domain + shift_domain,
            aggregates=[
                "planned_qty:sum",
                "good_qty:sum",
                "rework_qty:sum",
                "scrap_qty:sum",
                "downtime_minutes:sum",
            ],
        )
        planned, good, rework, scrap, downtime = (
            tuple(value or 0 for value in report_values[0]) if report_values else (0, 0, 0, 0, 0)
        )
        zones = dict(
            self.env["deep.production.unit"]._read_group(
                domain, groupby=["physical_zone"], aggregates=["__count"]
            )
        )
        alerts.sort(key=lambda row: 0 if row["severity"] == "critical" else 1)
        return {
            "company": self.env.company.name,
            "date": str(today),
            "updated": str(fields.Datetime.now()),
            "active_mos": count("mrp.production", active),
            "open_kits": count("deep.material.kit", [("state", "not in", ["issued", "cancel"])]),
            "open_breakdowns": count("deep.downtime.event", [("state", "=", "open")]),
            "blocking_cases": count(
                "deep.nonconformance", [("state", "!=", "closed"), ("blocking", "=", True)]
            ),
            "waiting_shifts": count("deep.shift.report", [("state", "=", "submitted")]),
            "waiting_handovers": count("deep.wip.handover", [("state", "=", "sent")]),
            "reported_good": good,
            "reported_rework": rework,
            "reported_scrap": scrap,
            "reported_downtime": downtime,
            "reported_attainment": round(good / planned * 100, 1) if planned else None,
            "zones": [
                {"name": label, "quantity": zones.get(key, 0)}
                for key, label in [
                    ("line", "Assembly line"),
                    ("hold", "Quality hold"),
                    ("rework", "Product rework"),
                    ("finished", "Finished goods"),
                ]
            ],
            "alerts": alerts[:100],
            "kits": kit_rows,
            "dispatch": [
                {
                    "id": order.id,
                    "name": order.name,
                    "product": order.product_id.display_name,
                    "quantity": order.product_qty,
                    "priority": order.deep_priority,
                    "promise": str(order.deep_promise_date or ""),
                    "state": order.state,
                    "progress": round(
                        len(order.workorder_ids.filtered(lambda work: work.state == "done"))
                        / len(order.workorder_ids)
                        * 100,
                        1,
                    )
                    if order.workorder_ids
                    else 0,
                }
                for order in orders
            ],
            "shifts": [
                {
                    "id": row.id,
                    "name": row.name,
                    "department": row.department_id.name,
                    "mo": row.production_id.name,
                    "good": row.good_qty,
                    "rework": row.rework_qty,
                    "scrap": row.scrap_qty,
                    "downtime": row.downtime_minutes,
                    "state": row.state,
                }
                for row in records("deep.shift.report", limit=30)
            ],
            "maintenance": [
                {
                    "id": row.id,
                    "name": row.name,
                    "center": row.workcenter_id.name,
                    "reason": row.reason_id.name,
                    "hours": round(row.duration_hours, 2),
                    "technician": row.technician_id.name or "Unassigned",
                    "expected": str(row.expected_end),
                    "state": row.state,
                }
                for row in breakdowns
            ],
            "quality": [
                {
                    "id": row.id,
                    "name": row.name,
                    "unit": row.unit_id.name or "General case",
                    "severity": row.severity,
                    "blocking": row.blocking,
                    "owner": row.owner_id.name,
                    "due": str(row.due_date),
                    "state": row.state,
                }
                for row in cases
            ],
            "contracts": [
                {
                    "id": row.id,
                    "name": row.name,
                    "contract": row.contract_id.reference,
                    "customer": row.contract_id.customer_id.name,
                    "product": row.product_id.default_code or row.product_id.name,
                    "quantity": row.quantity,
                    "delivered": row.delivered_qty,
                    "remaining": row.remaining_qty,
                    "due": str(row.due_date),
                    "state": row.delivery_status,
                }
                for row in milestones
            ],
        }

    @api.model
    def action_export(self):
        data = self.metrics()
        rows = [
            [row["severity"], row["title"], row["detail"], row["model"], row["id"]]
            for row in data["alerts"]
        ]
        return export_xlsx(
            self.env["res.company"].browse(self.env.company.id),
            "Operations_Action_List.xlsx",
            ["Severity", "Action", "Detail", "Record Type", "Record ID"],
            rows,
        )
