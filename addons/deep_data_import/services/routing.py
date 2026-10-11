from datetime import date

from odoo.exceptions import UserError


class BomRoutingHandlers:
    def _boms(self, r):
        parent, child = self.product(r["parent"]), self.product(r["component"])
        c = self.batch.company_id
        if parent == child:
            raise ValueError("A product cannot contain itself.")
        uom = self.find("uom.uom", [("name", "=", r["uom"])], "component unit")
        uom._compute_quantity(1, child.uom_id)
        bom = self.env["mrp.bom"].search(
            [
                ("product_tmpl_id", "=", parent.product_tmpl_id.id),
                ("company_id", "=", c.id),
                ("deep_revision", "=", r["revision"]),
            ]
        )
        if len(bom) > 1:
            raise ValueError("Ambiguous BOM revision.")
        if not bom:
            bom = self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": parent.product_tmpl_id.id,
                    "product_id": parent.id,
                    "company_id": c.id,
                    "deep_revision": r["revision"],
                    "deep_effective_date": date.fromisoformat(r["effective_date"][:10])
                    if r["effective_date"]
                    else False,
                    "type": "normal",
                }
            )
        operation = (
            self.find(
                "mrp.routing.workcenter",
                [("bom_id", "=", bom.id), ("deep_code", "=", r["operation"])],
                "BOM operation",
            )
            if r["operation"]
            else False
        )
        scrap = self.number(r["scrap_pct"] or 0)
        if scrap >= 100:
            raise ValueError("Scrap must be below 100%.")
        return self.upsert(
            "mrp.bom.line",
            [
                ("bom_id", "=", bom.id),
                ("product_id", "=", child.id),
                ("operation_id", "=", operation.id if operation else False),
            ],
            {
                "bom_id": bom.id,
                "product_id": child.id,
                "product_qty": self.number(r["quantity"], 0.000001),
                "product_uom_id": uom.id,
                "operation_id": operation.id if operation else False,
                "deep_scrap_pct": scrap,
            },
        )

    def _routing(self, r):
        bom = self.bom(r["parent"])
        center = self.find(
            "mrp.workcenter",
            [("code", "=", r["workcenter"]), ("company_id", "=", self.batch.company_id.id)],
            "work center",
        )
        if r["checkpoint"] not in ("normal", "serialize", "test", "release"):
            raise ValueError("Invalid checkpoint.")
        return self.upsert(
            "mrp.routing.workcenter",
            [("bom_id", "=", bom.id), ("deep_code", "=", r["code"])],
            {
                "bom_id": bom.id,
                "name": r["name"],
                "deep_code": r["code"],
                "workcenter_id": center.id,
                "sequence": int(r["sequence"]),
                "time_mode": "manual",
                "time_cycle_manual": self.number(r["cycle_minutes"]),
                "deep_setup": self.number(r["setup_minutes"]),
                "deep_cleanup": self.number(r["cleanup_minutes"]),
                "deep_batch_size": self.number(r["batch_size"]),
                "deep_operator_count": int(self.number(r["operator_count"], 1)),
                "deep_checkpoint": r["checkpoint"],
            },
        )

    def _operation_times(self, r):
        op = self.find(
            "mrp.routing.workcenter",
            [("bom_id", "=", self.bom(r["parent"]).id), ("deep_code", "=", r["code"])],
            "operation",
        )
        op.write(
            {
                "time_mode": "manual",
                "time_cycle_manual": self.number(r["cycle_minutes"]),
                "deep_setup": self.number(r["setup_minutes"]),
                "deep_cleanup": self.number(r["cleanup_minutes"]),
                "deep_batch_size": self.number(r["batch_size"]),
            }
        )
        return "updated"

    def check_cycles(self):
        edges = {}
        for bom in self.env["mrp.bom"].search(
            [("company_id", "=", self.batch.company_id.id), ("active", "=", True)]
        ):
            for p in bom.product_id or bom.product_tmpl_id.product_variant_ids:
                edges.setdefault(p.id, set()).update(bom.bom_line_ids.product_id.ids)
        done = set()

        def visit(node, path):
            if node in path:
                raise UserError("The imported BOM introduces a circular dependency.")
            if node in done:
                return
            for child in edges.get(node, ()):
                visit(child, path | {node})
            done.add(node)

        for node in edges:
            visit(node, set())
