class MasterDataHandlers:
    def _items(self, r):
        c = self.batch.company_id
        if r["make_buy"] not in ("make", "buy") or r["tracking"] not in ("none", "lot", "serial"):
            raise ValueError("Invalid make/buy or tracking.")
        if r["active"] not in ("true", "false", "1", "0"):
            raise ValueError("Active must be true/false or 1/0.")
        uom = self.find("uom.uom", [("name", "=", r["uom"])], "unit of measure")
        category = (
            self.find("product.category", [("name", "=", r["category"])], "product category")
            if r["category"]
            else self.env.ref("product.product_category_goods")
        )
        family = (
            self.find(
                "deep.product.family",
                [("code", "=", r["family"]), ("company_id", "=", c.id)],
                "family",
            )
            if r["family"]
            else False
        )
        return self.upsert(
            "product.product",
            [
                ("default_code", "=", r["code"]),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", c.id),
            ],
            {
                "default_code": r["code"],
                "name": r["description"],
                "company_id": c.id,
                "type": "consu",
                "is_storable": True,
                "uom_id": uom.id,
                "categ_id": category.id,
                "deep_make_buy": r["make_buy"],
                "tracking": r["tracking"],
                "deep_family_id": family.id if family else False,
                "standard_price": self.number(r["standard_cost"] or 0),
                "active": r["active"] in ("true", "1"),
            },
        )

    def _workcenters(self, r):
        vals = {
            "name": r["name"],
            "code": r["code"],
            "company_id": self.batch.company_id.id,
            "time_efficiency": self.number(r["efficiency"], 0.001),
            "time_start": self.number(r["setup_minutes"]),
            "time_stop": self.number(r["cleanup_minutes"]),
            "costs_hour": self.number(r["cost_hour"]),
        }
        cap = self.number(r["capacity"], 0.000001)
        center = self.env["mrp.workcenter"].search(
            [("code", "=", r["code"]), ("company_id", "=", self.batch.company_id.id)]
        )
        if center and self.batch.mode != "upsert":
            raise ValueError("Work center already exists.")
        if len(center) > 1:
            raise ValueError("Ambiguous work center.")
        result = "updated" if center else "created"
        if center:
            center.write(vals)
        else:
            center = self.env["mrp.workcenter"].create(vals)
        uom = self.env.ref("uom.product_uom_unit")
        capacity = center.capacity_ids.filtered(
            lambda p: not p.product_id and p.product_uom_id == uom
        )
        if capacity:
            capacity.write({"capacity": cap})
        else:
            self.env["mrp.workcenter.capacity"].create(
                {"workcenter_id": center.id, "product_uom_id": uom.id, "capacity": cap}
            )
        return result

    def _vendors(self, r):
        return self.upsert(
            "res.partner",
            [
                ("ref", "=", r["code"]),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.batch.company_id.id),
            ],
            {
                "ref": r["code"],
                "name": r["name"],
                "email": r["email"],
                "company_id": self.batch.company_id.id,
                "supplier_rank": 1,
                "deep_default_lead_days": int(self.number(r["lead_days"] or 0)),
            },
        )

    def _suppliers(self, r):
        p = self.product(r["item"])
        vendor = self.find(
            "res.partner",
            [
                ("ref", "=", r["vendor_code"]),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.batch.company_id.id),
            ],
            "vendor",
        )
        qty = self.number(r["minimum_qty"])
        return self.upsert(
            "product.supplierinfo",
            [
                ("product_tmpl_id", "=", p.product_tmpl_id.id),
                ("partner_id", "=", vendor.id),
                ("min_qty", "=", qty),
                ("company_id", "=", self.batch.company_id.id),
            ],
            {
                "product_tmpl_id": p.product_tmpl_id.id,
                "partner_id": vendor.id,
                "company_id": self.batch.company_id.id,
                "min_qty": qty,
                "price": self.number(r["price"]),
                "delay": int(self.number(r["lead_days"]))
                if r["lead_days"]
                else vendor.deep_default_lead_days,
            },
        )
