import hashlib
import json
from odoo import fields
from odoo.addons.deep_core.security import internal
from .client import SAPError
from .normalization import document_lines, open_quantity, number, sap_date


class SynchronizationService:
    def __init__(self, env, profile):
        self.env = env(su=True)(
            context={**env.context, "allowed_company_ids": profile.company_id.ids}
        )
        self.profile = self.env["deep.sap.profile"].browse(profile.id)
        self.company = profile.company_id
        self.now = fields.Datetime.now()
        self.maps = {record.sap_code: record for record in self.profile.warehouse_ids}
        self.uoms = {record.sap_name: record for record in self.profile.uom_ids}

    def fetch(self, client):
        payload = {"items": client.collection("Items", {"$orderby": "ItemCode"})}
        if self.profile.sync_partners:
            payload["partners"] = client.collection("BusinessPartners", {"$orderby": "CardCode"})
        for flag, key, resource in [
            (self.profile.sync_purchase, "purchase", "PurchaseOrders"),
            (self.profile.sync_sales, "sales", "Orders"),
        ]:
            if flag:
                payload[key] = client.collection(
                    resource,
                    {
                        "$filter": "DocumentStatus eq 'bost_Open' and Cancelled eq 'tNO'",
                        "$orderby": "DocEntry",
                    },
                )
        if self.profile.sync_boms:
            payload["boms"] = client.collection("ProductTrees", {"$orderby": "TreeCode"})
        return payload

    def upsert(self, model, identity, values):
        identity = [("profile_id", "=", self.profile.id)] + identity
        record = self.env[model].search(identity, limit=1)
        values = {**values, "profile_id": self.profile.id, "company_id": self.company.id}
        if record:
            internal(record).write(values)
        else:
            record = internal(self.env[model]).create(values)
        return record

    def item(self, code):
        record = self.env["deep.sap.item"].search(
            [("profile_id", "=", self.profile.id), ("sap_code", "=", code)], limit=1
        )
        if not record:
            raise SAPError(
                "UNMAPPED_ITEM", "SAP item is not bound to a native product: " + str(code)
            )
        return record

    def items(self, rows):
        touched = set()
        for row in rows:
            if row.get("InventoryItem") != "tYES":
                continue
            code, unit_name = row.get("ItemCode"), row.get("InventoryUOM") or ""
            if not code or not row.get("ItemName") or not unit_name or unit_name not in self.uoms:
                raise SAPError(
                    "ITEM_UNIT_MAPPING",
                    "Map the SAP inventory unit before importing item "
                    + str(code or "(missing code)"),
                )
            unit = self.uoms[unit_name]
            existing = self.env["deep.sap.item"].search(
                [("profile_id", "=", self.profile.id), ("sap_code", "=", code)], limit=1
            )
            product = (
                existing.product_id
                if existing
                else self.env["product.product"]
                .with_context(active_test=False)
                .search(
                    [
                        ("default_code", "=", code),
                        "|",
                        ("company_id", "=", False),
                        ("company_id", "=", self.company.id),
                    ]
                )
            )
            if len(product) > 1:
                raise SAPError("AMBIGUOUS_ITEM", "Multiple native products match SAP item " + code)
            tracking = (
                "serial"
                if row.get("ManageSerialNumbers") == "tYES"
                else "lot"
                if row.get("ManageBatchNumbers") == "tYES"
                else "none"
            )
            if product and (
                product.uom_id != unit.uom_id
                or product.tracking != tracking
                or (
                    existing
                    and (
                        existing.sap_uom != unit_name
                        or existing.quantity_factor != unit.quantity_factor
                    )
                )
            ):
                raise SAPError(
                    "ITEM_IDENTITY_CONFLICT",
                    "Resolve the unit/tracking migration explicitly for SAP item " + code,
                )
            if not product:
                product = self.env["product.product"].create(
                    {
                        "name": row["ItemName"],
                        "default_code": code,
                        "company_id": self.company.id,
                        "type": "consu",
                        "is_storable": True,
                        "uom_id": unit.uom_id.id,
                        "tracking": tracking,
                        "purchase_ok": row.get("PurchaseItem") == "tYES",
                        "sale_ok": row.get("SalesItem") == "tYES",
                        "deep_make_buy": "buy" if row.get("PurchaseItem") == "tYES" else "make",
                    }
                )
            # Existing master identity, approvals, prices and routing stay native-controlled.
            item = self.upsert(
                "deep.sap.item",
                [("sap_code", "=", code)],
                {
                    "sap_code": code,
                    "sap_uom": unit_name,
                    "quantity_factor": unit.quantity_factor,
                    "product_id": product.id,
                    "last_seen": self.now,
                },
            )
            warehouses = row.get("ItemWarehouseInfoCollection")
            if not isinstance(warehouses, list):
                raise SAPError(
                    "WAREHOUSE_SCHEMA", "SAP warehouse stock was not returned for item " + code
                )
            seen_codes = set()
            for stock in warehouses:
                mapping = self.maps.get(stock.get("WarehouseCode"))
                if not mapping:
                    continue
                if mapping.sap_code in seen_codes:
                    raise SAPError(
                        "DUPLICATE_STOCK", "SAP returned duplicate warehouse stock for " + code
                    )
                seen_codes.add(mapping.sap_code)
                values = {
                    "item_id": item.id,
                    "mapping_id": mapping.id,
                    "on_hand": number(stock.get("InStock"), "on hand", negative=True)
                    * unit.quantity_factor,
                    "committed": number(stock.get("Committed"), "committed") * unit.quantity_factor,
                    "ordered": number(stock.get("Ordered"), "ordered") * unit.quantity_factor,
                    "observed_at": self.now,
                }
                snapshot = self.upsert(
                    "deep.sap.stock",
                    [("item_id", "=", item.id), ("mapping_id", "=", mapping.id)],
                    values,
                )
                touched.add(snapshot.id)
            if seen_codes != set(self.maps):
                raise SAPError(
                    "WAREHOUSE_MISSING",
                    "A mapped SAP warehouse is missing from the stock response for " + code,
                )
        old = self.env["deep.sap.stock"].search(
            [("profile_id", "=", self.profile.id), ("id", "not in", list(touched))]
        )
        # Do not leave omitted items looking fresh; their previous snapshot is explicitly stale.
        internal(old).write({"observed_at": False})
        return len(touched)

    def partners(self, rows):
        for row in rows:
            code = row.get("CardCode")
            if not code or not row.get("CardName"):
                raise SAPError("PARTNER_IDENTITY", "SAP business partner identity is incomplete.")
            bound = self.env["deep.sap.partner"].search(
                [("profile_id", "=", self.profile.id), ("sap_code", "=", code)], limit=1
            )
            partner = bound.partner_id
            if not partner:
                matches = self.env["res.partner"].search(
                    [
                        ("ref", "=", code),
                        "|",
                        ("company_id", "=", False),
                        ("company_id", "=", self.company.id),
                    ]
                )
                if len(matches) > 1:
                    raise SAPError(
                        "AMBIGUOUS_PARTNER", "Multiple native partners match SAP code " + code
                    )
                partner = matches or self.env["res.partner"].create(
                    {
                        "name": row["CardName"],
                        "ref": code,
                        "company_id": self.company.id,
                        "supplier_rank": 1 if row.get("CardType") == "cSupplier" else 0,
                        "customer_rank": 1 if row.get("CardType") == "cCustomer" else 0,
                    }
                )
            self.upsert(
                "deep.sap.partner",
                [("sap_code", "=", code)],
                {"sap_code": code, "partner_id": partner.id, "kind": row.get("CardType", "")},
            )
        return len(rows)

    def documents(self, rows, sales=False):
        model = "deep.sap.sales.line" if sales else "deep.sap.purchase.line"
        seen, keys = set(), set()
        for doc in rows:
            for row in document_lines(doc):
                mapping = self.maps.get(row.get("WarehouseCode"))
                if not mapping:
                    continue
                item = self.item(row["ItemCode"])
                quantity = open_quantity(row) * item.quantity_factor
                if quantity <= 0:
                    continue
                if doc.get("DocEntry") is None or row.get("LineNum") is None:
                    raise SAPError("DOCUMENT_IDENTITY", "SAP document/line key is missing.")
                identity = [
                    ("doc_entry", "=", int(doc["DocEntry"])),
                    ("line_number", "=", int(row["LineNum"])),
                ]
                key = (int(doc["DocEntry"]), int(row["LineNum"]))
                if key in keys:
                    raise SAPError(
                        "DUPLICATE_DOCUMENT",
                        "SAP returned a repeated document line; refresh was rolled back.",
                    )
                keys.add(key)
                due = sap_date(row.get("ShipDate") or doc.get("DocDueDate"))
                values = {
                    "doc_entry": int(doc["DocEntry"]),
                    "doc_number": str(doc.get("DocNum", "")),
                    "line_number": int(row["LineNum"]),
                    "item_id": item.id,
                    "quantity": quantity,
                    "due_date": due,
                    "observed_at": self.now,
                    "current": True,
                }
                if sales:
                    values["customer_code"] = doc.get("CardCode", "")
                else:
                    values.update(
                        {"vendor_code": doc.get("CardCode", ""), "mapping_id": mapping.id}
                    )
                record = self.upsert(model, identity, values)
                seen.add(record.id)
                if sales:
                    demand_values = {
                        "name": "SAP SO " + values["doc_number"] + " / " + str(row["LineNum"]),
                        "company_id": self.company.id,
                        "product_id": item.product_id.id,
                        "category": "firm",
                        "quantity": quantity,
                        "required_date": due,
                        "confidence": 100,
                        "contract": "SAP SO " + values["doc_number"],
                        "external_id": "SAP:"
                        + str(self.profile.id)
                        + ":SO:"
                        + str(doc["DocEntry"])
                        + ":"
                        + str(row["LineNum"]),
                        "deep_sap_sales_line_id": record.id,
                    }
                    demand = record.demand_id
                    if demand:
                        changed = (
                            demand.product_id != item.product_id
                            or demand.quantity != quantity
                            or demand.required_date != due
                        )
                        if changed and demand._is_frozen():
                            raise SAPError(
                                "FROZEN_DEMAND_CONFLICT",
                                "SAP changed released or reviewed sales demand. Resolve an explicit planning amendment for SO "
                                + values["doc_number"],
                            )
                        if changed:
                            internal(demand).write(demand_values)
                    else:
                        demand = internal(self.env["deep.demand"]).create(demand_values)
                        internal(record).write({"demand_id": demand.id})
        for missing in self.env[model].search(
            [
                ("profile_id", "=", self.profile.id),
                ("current", "=", True),
                ("id", "not in", list(seen)),
            ]
        ):
            if sales and missing.demand_id and not missing.demand_id._is_frozen():
                internal(missing.demand_id).unlink()
            internal(missing).write({"current": False, "observed_at": self.now})
        return len(seen)

    def boms(self, rows):
        for row in rows:
            item = self.item(row.get("TreeCode"))
            components = []
            for component in row.get("ProductTreeLines", []):
                if component.get("ItemType", "pit_Item") != "pit_Item":
                    continue  # SAP resource rows stay in native routing/capacity configuration.
                bound = self.item(component.get("ItemCode"))
                components.append(
                    {
                        "product_id": bound.product_id.id,
                        "quantity": number(component.get("Quantity"), "BOM component")
                        * bound.quantity_factor,
                    }
                )
            if not components:
                raise SAPError("BOM_EMPTY", "SAP BOM has no bound stock components.")
            quantity = number(row.get("Quantity"), "BOM parent") * item.quantity_factor
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"quantity": quantity, "components": components}, sort_keys=True
                ).encode()
            ).hexdigest()
            values = {
                "item_id": item.id,
                "quantity": quantity,
                "components": components,
                "fingerprint": fingerprint,
                "observed_at": self.now,
            }
            existing = self.env["deep.sap.bom.snapshot"].search(
                [("profile_id", "=", self.profile.id), ("item_id", "=", item.id)], limit=1
            )
            if existing and existing.fingerprint != fingerprint:
                values["change_id"] = False
            self.upsert("deep.sap.bom.snapshot", [("item_id", "=", item.id)], values)
        return len(rows)

    def apply(self, payload):
        # Caller wraps this whole operation in one native database savepoint.
        counts = {"stock_snapshots": self.items(payload["items"])}
        for key in ("partners", "purchase", "sales", "boms"):
            if key in payload:
                counts[key] = (
                    self.documents(payload[key], sales=key == "sales")
                    if key in ("purchase", "sales")
                    else getattr(self, key)(payload[key])
                )
        # All draft plans must recalculate when external stock/supply is refreshed.
        plans = self.env["deep.mps.plan"].search(
            [
                ("company_id", "=", self.company.id),
                ("state", "=", "draft"),
                ("deep_sap_profile_id", "=", self.profile.id),
            ]
        )
        internal(plans).write({"calculated_at": False, "warnings_acknowledged": False})
        return counts
