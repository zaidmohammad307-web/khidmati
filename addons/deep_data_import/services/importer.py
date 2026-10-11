"""Import coordinator: native ORM operations, strict identities, full rollback on errors."""

import math

from odoo.exceptions import UserError

from .masters import MasterDataHandlers
from .parser import parse_file
from .routing import BomRoutingHandlers
from .transactions import TransactionHandlers

HEADERS = {
    "items": [
        "code",
        "description",
        "category",
        "uom",
        "make_buy",
        "tracking",
        "family",
        "standard_cost",
        "active",
    ],
    "boms": [
        "parent",
        "component",
        "quantity",
        "uom",
        "operation",
        "revision",
        "effective_date",
        "scrap_pct",
    ],
    "workcenters": [
        "code",
        "name",
        "capacity",
        "efficiency",
        "setup_minutes",
        "cleanup_minutes",
        "cost_hour",
    ],
    "routing": [
        "parent",
        "sequence",
        "code",
        "name",
        "workcenter",
        "cycle_minutes",
        "setup_minutes",
        "cleanup_minutes",
        "batch_size",
        "operator_count",
        "checkpoint",
    ],
    "operation_times": [
        "parent",
        "code",
        "cycle_minutes",
        "setup_minutes",
        "cleanup_minutes",
        "batch_size",
    ],
    "vendors": ["code", "name", "email", "lead_days"],
    "suppliers": ["item", "vendor_code", "price", "lead_days", "minimum_qty"],
    "inventory": ["item", "location", "lot", "counted_quantity"],
    "demand": [
        "external_id",
        "item",
        "category",
        "required_date",
        "quantity",
        "confidence",
        "contract",
        "milestone",
    ],
    "serials": ["serial", "item"],
}
KEYS = {
    "items": ["code"],
    "boms": ["parent", "component", "revision", "operation"],
    "workcenters": ["code"],
    "routing": ["parent", "code"],
    "operation_times": ["parent", "code"],
    "vendors": ["code"],
    "suppliers": ["item", "vendor_code", "minimum_qty"],
    "inventory": ["item", "location", "lot"],
    "demand": ["external_id"],
    "serials": ["serial", "item"],
}


class ImportService(MasterDataHandlers, BomRoutingHandlers, TransactionHandlers):
    def __init__(self, env, batch):
        self.env, self.batch = env, batch

    def parse(self, payload):
        return parse_file(payload, self.batch.filename, HEADERS[self.batch.kind])

    def number(self, value, minimum=0):
        n = float(value)
        if not math.isfinite(n) or n < minimum:
            raise ValueError("Invalid number.")
        return n

    def find(self, model, domain, label):
        r = self.env[model].with_context(active_test=False).search(domain)
        if len(r) != 1:
            raise ValueError("Expected one " + label)
        return r

    def product(self, code):
        return self.find(
            "product.product",
            [
                ("default_code", "=", code),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.batch.company_id.id),
            ],
            "item " + code,
        )

    def bom(self, code):
        p = self.product(code)
        return self.find(
            "mrp.bom",
            [
                ("product_tmpl_id", "=", p.product_tmpl_id.id),
                ("company_id", "=", self.batch.company_id.id),
                ("active", "=", True),
            ],
            "active BOM " + code,
        )

    def upsert(self, model, domain, vals):
        record = self.env[model].with_context(active_test=False).search(domain)
        if len(record) > 1:
            raise ValueError("Ambiguous existing master identity.")
        if record:
            if self.batch.mode != "upsert":
                raise ValueError(
                    "Record already exists; choose Create / Update to revise master data."
                )
            record.write(vals)
            return "updated"
        self.env[model].create(vals)
        return "created"

    def apply(self, rows):
        seen = set()
        counts = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
        for number, row in rows:
            key = tuple(row[h] for h in KEYS[self.batch.kind])
            if not all(key) and self.batch.kind not in ("boms", "inventory"):
                raise UserError(f"Row {number}: key fields are required.")
            if key in seen:
                raise UserError(f"Row {number}: duplicate import identity {key}.")
            seen.add(key)
            try:
                result = getattr(self, "_" + self.batch.kind)(row)
            except (ValueError, TypeError, UserError) as e:
                raise UserError(f"Row {number}: {e}") from e
            counts[result] += 1
        if self.batch.kind == "boms":
            self.check_cycles()
        return counts
