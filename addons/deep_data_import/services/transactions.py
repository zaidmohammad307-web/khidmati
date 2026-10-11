from datetime import date


class TransactionHandlers:
    def _inventory(self, r):
        p = self.product(r["item"])
        c = self.batch.company_id
        location = self.find(
            "stock.location",
            [
                ("complete_name", "=", r["location"]),
                ("company_id", "=", c.id),
                ("usage", "=", "internal"),
            ],
            "internal location",
        )
        lot = (
            self.find(
                "stock.lot",
                [("name", "=", r["lot"]), ("product_id", "=", p.id), ("company_id", "=", c.id)],
                "lot",
            )
            if r["lot"]
            else False
        )
        if p.tracking != "none" and not lot:
            raise ValueError("Tracked counts require an existing lot/serial.")
        quantity = self.number(r["counted_quantity"])
        if p.tracking == "serial" and quantity not in (0, 1):
            raise ValueError("Serial count must be zero or one.")
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", p.id),
                ("location_id", "=", location.id),
                ("lot_id", "=", lot.id if lot else False),
                ("owner_id", "=", False),
                ("package_id", "=", False),
            ]
        )
        if len(quant) > 1:
            raise ValueError("Multiple inventory quants match this identity.")
        if not quant:
            quant = (
                self.env["stock.quant"]
                .with_context(inventory_mode=True)
                .create(
                    {
                        "product_id": p.id,
                        "location_id": location.id,
                        "lot_id": lot.id if lot else False,
                    }
                )
            )
        quant.with_context(inventory_mode=True).write({"inventory_quantity": quantity})
        quant.action_apply_inventory()
        return "updated"

    def _demand(self, r):
        p = self.product(r["item"])
        confidence = self.number(r["confidence"] or 100)
        if r["category"] not in ("firm", "project", "forecast", "manual") or confidence > 100:
            raise ValueError("Invalid demand category/confidence.")
        return self.upsert(
            "deep.demand",
            [("external_id", "=", r["external_id"]), ("company_id", "=", self.batch.company_id.id)],
            {
                "name": r["external_id"],
                "external_id": r["external_id"],
                "company_id": self.batch.company_id.id,
                "product_id": p.id,
                "category": r["category"],
                "required_date": date.fromisoformat(r["required_date"][:10]),
                "quantity": self.number(r["quantity"], 0.000001),
                "confidence": confidence,
                "contract": r["contract"],
                "milestone": r["milestone"],
            },
        )

    def _serials(self, r):
        p = self.product(r["item"])
        if p.tracking != "serial":
            raise ValueError("Product must be serial tracked.")
        return self.upsert(
            "stock.lot",
            [
                ("name", "=", r["serial"]),
                ("product_id", "=", p.id),
                ("company_id", "=", self.batch.company_id.id),
            ],
            {"name": r["serial"], "product_id": p.id, "company_id": self.batch.company_id.id},
        )
