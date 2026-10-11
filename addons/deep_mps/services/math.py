"""Pure planning arithmetic: executable without an Odoo server."""

import calendar
import math
from datetime import timedelta


def period_end(start, horizon):
    if horizon == "daily":
        return start
    if horizon == "weekly":
        return start + timedelta(days=6)
    if horizon == "monthly":
        return start.replace(day=calendar.monthrange(start.year, start.month)[1])
    raise ValueError("Unsupported planning horizon.")


def demand_total(firm, forecast, manual, confidence, strategy):
    if min(firm, forecast, manual) < 0 or not 0 <= confidence <= 100:
        raise ValueError("Invalid demand.")
    if strategy not in ("consume", "add"):
        raise ValueError("Invalid forecast strategy.")
    nominal = (max(firm, forecast) if strategy == "consume" else firm + forecast) + manual
    weighted = (
        max(firm, forecast * confidence / 100)
        if strategy == "consume"
        else firm + forecast * confidence / 100
    ) + manual
    return nominal, weighted


def lot_size(net, minimum=0, multiple=0):
    """Round a positive net requirement up to the product's order policy.

    ``minimum`` is the smallest order (MOQ); ``multiple`` is the pack or batch
    increment applied after the minimum. Zero disables either rule.
    """
    if minimum < 0 or multiple < 0:
        raise ValueError("Lot sizes cannot be negative.")
    if net <= 0:
        return 0
    quantity = max(net, minimum)
    if multiple:
        # Round the ratio first so float noise (e.g. 0.30000000000000004) does not add a lot.
        quantity = math.ceil(round(quantity / multiple, 9)) * multiple
    return quantity


def bucket(beginning, receipts, demand, safety, minimum=0, multiple=0):
    planned = lot_size(max(0, demand + safety - beginning - receipts), minimum, multiple)
    return planned, beginning + receipts + planned - demand
