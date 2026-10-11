from datetime import datetime, time, timedelta

import pytz
from odoo.addons.deep_core.security import internal

from .math import operation_minutes


class CapacityService:
    def __init__(self, env):
        self.env = env

    def calculate(self, plan):
        internal(plan.capacity_ids).unlink()
        pending = self.env["mrp.workorder"].search(
            [("company_id", "=", plan.company_id.id), ("state", "not in", ["done", "cancel"])]
        )
        make = plan.requirement_ids.filtered(
            lambda r: r.kind == "make" and r.net > 0 and not r.production_id
        )
        centers = pending.workcenter_id | make.bom_id.operation_ids.workcenter_id
        rows, warnings = [], []
        for period in plan.period_ids:
            for center in centers:
                tz = pytz.timezone(center.resource_calendar_id.tz or "UTC")
                start = tz.localize(datetime.combine(period.start_date, time.min))
                end = tz.localize(datetime.combine(period.end_date + timedelta(days=1), time.min))
                utc_start = start.astimezone(pytz.UTC).replace(tzinfo=None)
                utc_end = end.astimezone(pytz.UTC).replace(tzinfo=None)
                available = center.resource_calendar_id.get_work_hours_count(
                    start, end, compute_leaves=True
                )
                minutes, labor = 0, 0
                skills = self.env["deep.operation.skill"]
                headcount = 0
                for r in make.filtered(
                    lambda r: period.start_date <= r.required_date <= period.end_date
                ):
                    for op in r.bom_id.operation_ids.filtered(lambda o: o.workcenter_id == center):
                        cap, setup, cleanup = center._get_capacity(
                            r.product_id, r.product_id.uom_id, r.bom_id.product_qty
                        )
                        duration = operation_minutes(
                            r.net,
                            op.time_cycle,
                            cap,
                            center.time_efficiency,
                            op.deep_setup if op.deep_setup >= 0 else setup,
                            op.deep_cleanup if op.deep_cleanup >= 0 else cleanup,
                            op.deep_batch_size,
                        )
                        minutes += duration
                        labor += duration / 60 * op.deep_operator_count
                        skills |= op.deep_skill_ids
                        headcount = max(headcount, op.deep_operator_count)
                for w in pending.filtered(lambda w: w.workcenter_id == center):
                    when = w.date_start or w.production_id.date_start
                    if period.start_date <= when.date() <= period.end_date:
                        duration = max(0, w.duration_expected - w.duration)
                        minutes += duration
                        labor += duration / 60 * w.operation_id.deep_operator_count
                        skills |= w.operation_id.deep_skill_ids
                        headcount = max(headcount, w.operation_id.deep_operator_count)
                shifts = self.env["deep.labor.shift"].search(
                    [
                        ("company_id", "=", plan.company_id.id),
                        ("workcenter_id", "=", center.id),
                        ("start", "<", utc_end),
                        ("end", ">", utc_start),
                    ]
                )
                qualified_hours, max_people = 0, 0
                for shift in shifts:
                    qualified = shift.employee_ids
                    for requirement in skills:
                        qualifications = self.env["deep.employee.skill"].search(
                            [
                                ("company_id", "=", plan.company_id.id),
                                ("skill_id", "=", requirement.skill_id.id),
                                ("level_id.rank", ">=", requirement.level_id.rank),
                                "|",
                                ("valid_until", "=", False),
                                ("valid_until", ">=", period.end_date),
                            ]
                        )
                        qualified &= qualifications.employee_id
                        headcount = max(headcount, requirement.operator_count)
                    overlap = max(
                        0,
                        (min(shift.end, utc_end) - max(shift.start, utc_start)).total_seconds()
                        / 3600,
                    )
                    qualified_hours += overlap * len(qualified)
                    max_people = max(max_people, len(qualified))
                shortage = minutes > 0 and (labor > qualified_hours or max_people < headcount)
                required = minutes / 60
                if shortage or required > available:
                    warnings.append(
                        f"{center.name} / {period.name}: machine or qualified labor overload"
                    )
                rows.append(
                    {
                        "plan_id": plan.id,
                        "period_id": period.id,
                        "workcenter_id": center.id,
                        "available_hours": available,
                        "required_hours": required,
                        "labor_hours": labor,
                        "qualified_hours": qualified_hours,
                        "labor_shortage": shortage,
                    }
                )
        internal(self.env["deep.capacity.snapshot"]).create(rows)
        internal(plan).write({"warnings": "\n".join(filter(None, [plan.warnings, *warnings]))})
