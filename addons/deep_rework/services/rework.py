from odoo.exceptions import UserError


class ReworkService:
    def __init__(self, env):
        self.env = env

    def ready(self, orders):
        orders._assignment()
        if any(not r.root_cause or not r.corrective_action for r in orders):
            raise UserError("Record root cause and corrective action before retest.")
        if any(not p.move_id or p.move_id.state != "done" for p in orders.part_ids):
            raise UserError("Complete all recorded replacement-part transfers.")
        orders._advance(["repairing"], "ready")
        orders.unit_id._set_state("retest", "line", "Repair complete; same-serial retest required")
        return True
