from datetime import timedelta

from odoo import Command, fields
from odoo.addons.deep_core.security import internal
from odoo.exceptions import UserError

from .math import bucket, demand_total, period_end


class MPSService:
    def __init__(self, env):
        self.env = env

    def calculate(self, plan):
        internal(plan.requirement_ids).unlink()
        internal(plan.line_ids).unlink()
        internal(plan.period_ids).unlink()
        rows = []
        start = plan.start_date
        for _ in range(plan.bucket_count):
            end = period_end(start, plan.horizon)
            rows.append(
                {"name": str(start), "plan_id": plan.id, "start_date": start, "end_date": end}
            )
            start = end + timedelta(days=1)
        periods = internal(self.env["deep.mps.period"]).create(rows)
        demands = self.env["deep.demand"].search(plan._deep_demand_domain(periods[-1].end_date))
        if any(d.released_plan_id and d.released_plan_id != plan for d in demands):
            raise UserError("A source demand was already released in another plan.")
        products = plan.product_ids | demands.product_id
        if not products:
            raise UserError("Select products or enter demand.")
        supplies = plan._deep_incoming_supply(products)
        rows = []
        for product in products:
            supply = supplies.get(product.id, [])
            safety = product.deep_safety_stock or plan.safety_stock
            beginning = plan._deep_available_stock(product) + sum(
                quantity for date, quantity in supply if date < plan.start_date
            )
            for period in periods:
                selected = demands.filtered(
                    lambda d: (
                        d.product_id == product
                        and period.start_date <= d.required_date <= period.end_date
                    )
                )
                firm = sum(d.quantity for d in selected if d.category in ("firm", "project"))
                forecast = sum(d.quantity for d in selected if d.category == "forecast")
                confidence = (
                    sum(d.quantity * d.confidence for d in selected if d.category == "forecast")
                    / forecast
                    if forecast
                    else 100
                )
                manual = sum(d.quantity for d in selected if d.category == "manual")
                total, weighted = demand_total(firm, forecast, manual, confidence, plan.strategy)
                receipts = sum(
                    quantity
                    for date, quantity in supply
                    if period.start_date <= date <= period.end_date
                )
                planned, balance = bucket(
                    beginning,
                    receipts,
                    total,
                    safety,
                    product.deep_lot_minimum,
                    product.deep_lot_multiple,
                )
                rows.append(
                    {
                        "plan_id": plan.id,
                        "period_id": period.id,
                        "product_id": product.id,
                        "firm": firm,
                        "forecast": forecast,
                        "manual": manual,
                        "confidence": confidence,
                        "weighted_demand": weighted,
                        "total_demand": total,
                        "beginning": beginning,
                        "receipts": receipts,
                        "planned": planned,
                        "balance": balance,
                    }
                )
                beginning = balance
        internal(self.env["deep.mps.line"]).create(rows)
        internal(plan).write(
            {
                "calculated_at": fields.Datetime.now(),
                "warnings": False,
                "source_demand_ids": [Command.set(demands.ids)],
            }
        )
