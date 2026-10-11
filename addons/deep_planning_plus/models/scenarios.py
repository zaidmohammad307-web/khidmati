from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.addons.deep_core.security import internal, lock, require_internal, require_role
from odoo.exceptions import UserError


class Scenario(models.Model):
    _name = "deep.plan.scenario"
    _description = "Recalculated MPS What-if Scenario"
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    base_plan_id = fields.Many2one("deep.mps.plan", required=True, check_company=True)
    preview_plan_id = fields.Many2one(
        "deep.mps.plan", readonly=True, check_company=True, copy=False
    )
    demand_factor = fields.Float(default=1, required=True)
    date_shift_days = fields.Integer()
    overtime_per_center = fields.Float(
        help="Additional assumed hours per center per bucket, for sensitivity comparison only."
    )
    notes = fields.Text()
    calculated_at = fields.Datetime(readonly=True)
    base_planned = fields.Float(compute="_summary")
    scenario_planned = fields.Float(compute="_summary")
    overload_hours = fields.Float(compute="_summary")
    shortage_lines = fields.Integer(compute="_summary")
    _valid = models.Constraint(
        "CHECK(demand_factor>0 AND overtime_per_center>=0)", "Invalid scenario assumptions."
    )

    @api.model_create_multi
    def create(self, values):
        if any(value.get("preview_plan_id") or value.get("calculated_at") for value in values):
            require_internal(self.env)
        return super().create(values)

    def write(self, values):
        if set(values) & {"preview_plan_id", "calculated_at"}:
            require_internal(self.env)
        result = super().write(values)
        if set(values) & {
            "base_plan_id",
            "demand_factor",
            "date_shift_days",
            "overtime_per_center",
            "company_id",
        }:
            internal(self).write({"calculated_at": False})
        return result

    @api.depends(
        "base_plan_id.line_ids.planned",
        "preview_plan_id.line_ids.planned",
        "preview_plan_id.requirement_ids.net",
        "preview_plan_id.capacity_ids.required_hours",
        "preview_plan_id.capacity_ids.available_hours",
        "overtime_per_center",
    )
    def _summary(self):
        for scenario in self:
            scenario.base_planned = sum(scenario.base_plan_id.line_ids.mapped("planned"))
            scenario.scenario_planned = sum(scenario.preview_plan_id.line_ids.mapped("planned"))
            scenario.shortage_lines = len(
                scenario.preview_plan_id.requirement_ids.filtered(
                    lambda row: row.kind == "buy" and row.net > 0
                )
            )
            scenario.overload_hours = sum(
                max(0, row.required_hours - row.available_hours - scenario.overtime_per_center)
                for row in scenario.preview_plan_id.capacity_ids
            )

    def _preview_source_values(self):
        self.ensure_one()
        return {}

    def action_calculate(self):
        require_role(self.env, "planner", "manager")
        for scenario in self:
            lock(scenario)
            base = scenario.base_plan_id
            if not base.calculated_at or not base.source_demand_ids:
                raise UserError("Calculate a base MPS plan with captured demand first.")
            plan = self.env["deep.mps.plan"].create(
                {
                    "name": scenario.name + " / Preview",
                    "company_id": scenario.company_id.id,
                    "warehouse_id": base.warehouse_id.id,
                    "start_date": base.start_date + timedelta(days=scenario.date_shift_days),
                    "horizon": base.horizon,
                    "bucket_count": base.bucket_count,
                    "strategy": base.strategy,
                    "safety_stock": base.safety_stock,
                    "product_ids": [Command.set(base.product_ids.ids)],
                    "deep_scenario_id": scenario.id,
                    **scenario._preview_source_values(),
                }
            )
            self.env["deep.demand"].create(
                [
                    {
                        "name": demand.name + " / Scenario",
                        "company_id": scenario.company_id.id,
                        "plan_id": plan.id,
                        "product_id": demand.product_id.id,
                        "category": demand.category,
                        "quantity": demand.quantity * scenario.demand_factor,
                        "confidence": demand.confidence,
                        "required_date": demand.required_date
                        + timedelta(days=scenario.date_shift_days),
                        "contract": demand.contract,
                        "milestone": demand.milestone,
                    }
                    for demand in base.source_demand_ids
                ]
            )
            plan.action_calculate()
            internal(scenario).write(
                {"preview_plan_id": plan.id, "calculated_at": fields.Datetime.now()}
            )
            self.env["deep.audit.event"]._record(
                scenario,
                "scenario_calculated",
                reason="Preview uses real MPS/MRP/calendars with isolated scenario demand; no operational orders released",
            )
        return True

    def action_open_preview(self):
        self.ensure_one()
        if not self.preview_plan_id:
            raise UserError("Calculate the scenario first.")
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.mps.plan",
            "res_id": self.preview_plan_id.id,
            "view_mode": "form",
        }


class Plan(models.Model):
    _inherit = "deep.mps.plan"
    deep_scenario_id = fields.Many2one(
        "deep.plan.scenario", readonly=True, check_company=True, copy=False
    )

    def _deep_demand_domain(self, end_date):
        domain = super()._deep_demand_domain(end_date)
        if self.deep_scenario_id:
            domain += [("plan_id", "=", self.id)]
        else:
            domain += ["|", ("plan_id", "=", False), ("plan_id.deep_scenario_id", "=", False)]
        return domain

    def action_release(self):
        if any(plan.deep_scenario_id for plan in self):
            raise UserError(
                "Scenario previews cannot release MOs or purchasing. Create a separate operational revision."
            )
        return super().action_release()


class Demand(models.Model):
    _inherit = "deep.demand"

    def _invalidate_draft_plans(self):
        scenario_demands = self.filtered(lambda demand: demand.plan_id.deep_scenario_id)
        internal(scenario_demands.plan_id).write(
            {"calculated_at": False, "warnings_acknowledged": False}
        )
        ordinary = self - scenario_demands
        if ordinary:
            return super(Demand, ordinary)._invalidate_draft_plans()
        return True
