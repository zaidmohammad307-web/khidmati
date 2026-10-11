"""Strict SAP payload normalization; inventory quantities are converted explicitly."""

import math
from datetime import date

from .client import SAPError


def number(value, label, negative=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise SAPError("DATA_QUANTITY", "Invalid SAP quantity: " + label) from None
    if not math.isfinite(result) or (result < 0 and not negative):
        raise SAPError("DATA_QUANTITY", "Invalid SAP quantity: " + label)
    return result


def document_lines(doc):
    rows = doc.get("DocumentLines")
    if not isinstance(rows, list):
        raise SAPError(
            "DATA_LINES",
            "SAP document lines were not returned; confirm Service Layer metadata and permissions.",
        )
    for line in rows:
        if line.get("ItemCode") and line.get("LineStatus", "bost_Open") == "bost_Open":
            yield line


def open_quantity(line):
    if line.get("RemainingOpenInventoryQuantity") is not None:
        return number(line["RemainingOpenInventoryQuantity"], "open inventory quantity")
    if line.get("RemainingOpenQuantity") is None:
        raise SAPError(
            "DATA_OPEN_QUANTITY",
            "SAP did not return the remaining open quantity; planned document quantity is never substituted.",
        )
    return number(line["RemainingOpenQuantity"], "open quantity") * number(
        line.get("UnitsOfMeasurment", 1), "document unit factor"
    )


def sap_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise SAPError("DATA_DATE", "SAP returned a missing or invalid required date.") from None
