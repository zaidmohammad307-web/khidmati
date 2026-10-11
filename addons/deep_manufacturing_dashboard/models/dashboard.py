from datetime import timedelta
from odoo import api, fields, models
from odoo.addons.deep_core.security import require_role


class Dashboard(models.AbstractModel):
    _name = "deep.manufacturing.dashboard"
    _description = "Live Manufacturing Cockpit Service"

    @api.model
    def metrics(self):
        require_role(self.env, "planner", "supervisor", "qa", "procurement", "manager")
        domain = [("company_id", "=", self.env.company.id)]
        prod = self.env["mrp.production"]
        units = self.env["deep.production.unit"]
        active = domain + [("state", "not in", ["done", "cancel"])]
        count = prod.search_count(active)
        totals = prod._read_group(active, aggregates=["product_qty:sum"])
        states = dict(units._read_group(domain, groupby=["state"], aggregates=["__count"]))
        now = fields.Datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        complete = prod.search_count(
            domain + [("state", "=", "done"), ("date_finished", ">=", today)]
        )
        late = prod.search_count(active + [("date_finished", "<", now)])
        summary = self.env["deep.quality.summary"]._read_group(
            domain, aggregates=["tested:sum", "first_pass:sum", "retested:sum", "retest_pass:sum"]
        )
        tested, first, retested, retest_pass = summary[0] if summary else (0, 0, 0, 0)
        plan = self.env["deep.mps.plan"].search(domain, order="id desc", limit=1)
        planned = sum(plan.line_ids.mapped("planned"))
        actual = sum(plan.line_ids.mapped("actual"))
        work = self.env["mrp.workorder"].search(
            domain + [("state", "not in", ["done", "cancel"])], order="date_start,id", limit=100
        )
        schedule = []
        for w in work:
            start = w.date_start or w.production_id.date_start
            end = w.date_finished or start + timedelta(minutes=w.duration_expected)
            schedule.append(
                {
                    "id": w.id,
                    "name": w.name,
                    "mo": w.production_id.name,
                    "center": w.workcenter_id.name,
                    "start": str(start),
                    "end": str(end),
                    "minutes": round(w.duration_expected, 1),
                    "state": w.state,
                }
            )
        station_groups = self.env["mrp.workorder"]._read_group(
            domain + [("state", "in", ["ready", "progress"])],
            groupby=["workcenter_id"],
            aggregates=["__count", "qty_production:sum"],
        )
        pareto = self.env["deep.quality.result"]._read_group(
            domain + [("passed", "=", False)], groupby=["failure_code"], aggregates=["__count"]
        )
        return {
            "active": count,
            "planned_units": totals[0][0] if totals else 0,
            "hold": states.get("hold", 0),
            "rework": states.get("rework", 0),
            "scrap": states.get("scrapped", 0),
            "completed_today": complete,
            "late_orders": late,
            "first_pass_yield": round(first / tested * 100, 1) if tested else None,
            "retest_success": round(retest_pass / retested * 100, 1) if retested else None,
            "attainment": round(actual / planned * 100, 1) if planned else None,
            "plan_id": plan.id,
            "plan": plan.name or "No Plan",
            "shortages": len(plan.requirement_ids.filtered("shortage")),
            "late_materials": len(
                plan.requirement_ids.filtered(
                    lambda r: r.shortage and r.expected_date > r.required_date
                )
            ),
            "capacity": [
                {
                    "id": c.id,
                    "center": c.workcenter_id.name,
                    "period": c.period_id.name,
                    "required": round(c.required_hours, 1),
                    "available": round(c.available_hours, 1),
                    "load": round(c.utilization, 1),
                    "overload": round(c.overload_hours, 1),
                    "labor_shortage": c.labor_shortage,
                }
                for c in plan.capacity_ids
            ],
            "schedule": schedule,
            "wip": [
                {"id": center.id, "name": center.name, "orders": n, "quantity": qty}
                for center, n, qty in station_groups
            ],
            "pareto": sorted(
                [{"code": code or "Uncategorized", "count": n} for code, n in pareto],
                key=lambda p: p["count"],
                reverse=True,
            )[:10],
            "matrix": {
                "periods": [p.name for p in plan.period_ids],
                "products": [
                    {
                        "name": p.display_name,
                        "id": p.id,
                        "cells": [
                            {
                                "planned": planning_line.planned,
                                "actual": planning_line.actual,
                                "balance": planning_line.balance,
                            }
                            for period in plan.period_ids
                            for planning_line in plan.line_ids
                            if planning_line.period_id == period and planning_line.product_id == p
                        ],
                    }
                    for p in plan.line_ids.product_id
                ],
            },
        }
