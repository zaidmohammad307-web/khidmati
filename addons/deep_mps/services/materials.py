from datetime import timedelta
from odoo import fields
from odoo.exceptions import UserError
from odoo.addons.deep_core.security import internal, lock


class MaterialService:
    """Simulation ledger uses upstream BOM explosion; release creates native MOs."""

    def __init__(self, env):
        self.env = env
        self.stock, self.receipts, self.boms = {}, {}, {}
        self.rows, self.warnings = [], set()

    def _supply(self, product, plan):
        if product.id in self.stock:
            return
        self.stock[product.id] = max(0, plan._deep_available_stock(product))
        self.receipts[product.id] = plan._deep_incoming_supply(product).get(product.id, [])

    def _visit(self, product, qty, line, when, path, ancestors=(), root=False):
        if product.id in ancestors:
            raise UserError("Circular BOM dependency: " + path)
        plan = line.plan_id
        self._supply(product, plan)
        stock = 0 if root else min(qty, self.stock[product.id])
        self.stock[product.id] -= stock
        net, receipts = qty - stock, 0
        if not root:
            for receipt in self.receipts[product.id]:
                if receipt[0] <= when:
                    used = min(net, receipt[1])
                    receipt[1] -= used
                    net -= used
                    receipts += used
        if product.id not in self.boms:
            self.boms[product.id] = (
                self.env["mrp.bom"]
                ._bom_find(product, company_id=plan.company_id.id, bom_type="normal")
                .get(product)
            )
        bom = self.boms[product.id]
        kind = "make" if bom or product.deep_make_buy == "make" else "buy"
        seller = product.seller_ids.filtered(
            lambda s: (not s.company_id or s.company_id == plan.company_id)
            and (not s.product_id or s.product_id == product)
            and (not s.date_start or s.date_start <= when)
            and (not s.date_end or s.date_end >= when)
        ).sorted(lambda s: (s.sequence, s.delay))[:1]
        lead = bom.produce_delay if bom else seller.delay if seller else 0
        eta = fields.Date.context_today(plan) + timedelta(days=lead)
        warning = ""
        if net > 0:
            if kind == "make" and not bom:
                warning = "Missing BOM"
            elif kind == "make" and not bom.operation_ids:
                warning = "Missing routing"
            elif kind == "buy" and not seller:
                warning = "Missing supplier / lead time"
            elif kind == "buy" and not lead:
                warning = "Missing supplier lead time"
            elif eta > when:
                warning = "Supply arrives after required date"
            if kind == "buy":
                self.warnings.add(product.display_name + ": BUY shortage " + str(round(net, 4)))
            if warning:
                self.warnings.add(product.display_name + ": " + warning)
        self.rows.append(
            {
                "plan_id": plan.id,
                "line_id": line.id,
                "product_id": product.id,
                "bom_id": bom.id if bom else False,
                "kind": kind,
                "path": path,
                "required_date": when,
                "gross": qty,
                "stock_allocated": stock,
                "receipt_allocated": receipts,
                "net": max(0, net),
                "supplier_id": seller.partner_id.id if seller else False,
                "lead_days": lead,
                "expected_date": eta,
                "shortage": kind == "buy" and net > 0,
                "warning": warning,
            }
        )
        if net > 0 and bom:
            factor = product.uom_id._compute_quantity(net, bom.product_uom_id) / bom.product_qty
            _, components = bom.explode(product, factor)
            for component, values in components:
                needed = component.product_uom_id._compute_quantity(
                    values["qty"], component.product_id.uom_id
                ) / (1 - component.deep_scrap_pct / 100)
                self._visit(
                    component.product_id,
                    needed,
                    line,
                    when - timedelta(days=lead),
                    path + " / " + (component.product_id.default_code or component.product_id.name),
                    ancestors + (product.id,),
                )

    def calculate(self, plan):
        internal(plan.requirement_ids).unlink()
        for line in plan.line_ids.sorted(
            lambda planning_line: (planning_line.period_id.start_date, planning_line.product_id.id)
        ):
            if line.planned > 0:
                self._visit(
                    line.product_id,
                    line.planned,
                    line,
                    line.period_id.end_date,
                    line.product_id.default_code or line.product_id.name,
                    root=True,
                )
        internal(self.env["deep.material.requirement"]).create(self.rows)
        internal(plan).write({"warnings": "\n".join(sorted(self.warnings))})

    def release(self, plan):
        lock(plan.source_demand_ids)
        if any(d.released_plan_id and d.released_plan_id != plan for d in plan.source_demand_ids):
            raise UserError("Demand was released by another planner.")
        make = plan.requirement_ids.filtered(lambda r: r.kind == "make" and r.net > 0)
        if any(not r.bom_id or not r.bom_id.operation_ids for r in make):
            raise UserError("Every MAKE requirement needs a BOM and routing.")
        # Explicit multilevel release uses make-to-stock routes to avoid a second native MTO explosion.
        mto = self.env.ref("stock.route_warehouse0_mto", raise_if_not_found=False)
        if mto and any(mto in r.product_id.route_ids for r in make):
            raise UserError(
                "Use make-to-stock routes for explicit MPS multilevel release; MTO would duplicate component MOs."
            )
        for r in make:
            if r.production_id:
                continue
            mo = self.env["mrp.production"].create(
                {
                    "product_id": r.product_id.id,
                    "product_qty": r.net,
                    "product_uom_id": r.product_id.uom_id.id,
                    "bom_id": r.bom_id.id,
                    "company_id": plan.company_id.id,
                    "picking_type_id": plan.warehouse_id.manu_type_id.id,
                    "date_start": str(r.required_date - timedelta(days=r.lead_days)) + " 06:00:00",
                    "origin": plan.name,
                    "deep_mps_line_id": r.line_id.id,
                    "deep_requirement_id": r.id,
                }
            )
            internal(r).write({"production_id": mo.id})
            self.env["deep.audit.event"]._record(mo, "mps_draft_mo", reason=plan.name)
        for line in plan.line_ids:
            requirements = plan.requirement_ids.filtered(
                lambda r: r.line_id == line and r.production_id
            )
            for requirement in requirements:
                parents = requirements.filtered(
                    lambda parent: parent != requirement
                    and requirement.path.startswith(parent.path + " / ")
                ).sorted(lambda parent: len(parent.path), reverse=True)
                if parents:
                    requirement.production_id.deep_parent_id = parents[0].production_id

        internal(plan.source_demand_ids).write({"released_plan_id": plan.id})
