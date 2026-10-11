from odoo import api, models
from odoo.addons.deep_core.security import lock, require_role
from odoo.exceptions import UserError


class Shopfloor(models.AbstractModel):
    _name = "deep.shopfloor"
    _description = "Shop Floor Application Services"

    @api.model
    def board(self, offset=0):
        require_role(self.env, "operator", "qa", "supervisor", "planner", "manager")
        offset = max(0, int(offset))
        orders = self.env["mrp.production"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("state", "not in", ["draft", "done", "cancel"]),
            ],
            order="date_start,id",
            limit=50,
            offset=offset,
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "product": p.product_id.display_name,
                "quantity": p.product_qty,
                "state": p.state,
                "units": [
                    {"id": u.id, "name": u.name, "state": u.state, "zone": u.physical_zone}
                    for u in p.deep_unit_ids
                ],
                "materials": p.deep_material_status(),
                "stations": [
                    {
                        "id": w.id,
                        "name": w.name,
                        "code": w.operation_id.deep_code or "",
                        "center": w.workcenter_id.name,
                        "state": w.state,
                        "checkpoint": w.deep_checkpoint,
                        "expected": round(w.duration_expected, 1),
                        "actual": round(w.duration, 1),
                    }
                    for w in p.workorder_ids.sorted("sequence")
                ],
            }
            for p in orders
        ]

    @api.model
    def station_action(self, work_id, action, quantity=1, key=""):
        require_role(self.env, "operator", "supervisor", "manager")
        work = self.env["mrp.workorder"].browse(work_id).exists()
        if not work or work.company_id != self.env.company:
            raise UserError("Unknown work order in the current company.")
        lock(work)
        if action == "start":
            return work.button_start()
        if action == "finish":
            return work.button_finish()
        if action == "serialize":
            return work.action_deep_serialize(quantity, key)
        raise UserError("Unsupported station action.")

    @api.model
    def release(self, unit_ids):
        units = self.env["deep.production.unit"].browse(unit_ids).exists()
        if len(units) != len(set(unit_ids)) or any(u.company_id != self.env.company for u in units):
            raise UserError("Select existing units from the current company.")
        units.action_prepare_selected()
        units.action_release()
        return units.action_finish_selected()

    @api.model
    def print_labels(self, unit_ids):
        units = self.env["deep.production.unit"].browse(unit_ids).exists()
        if any(u.company_id != self.env.company for u in units):
            raise UserError("Select units from the current company.")
        return units.action_print()
