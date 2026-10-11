"""Pure planning arithmetic: executable without an Odoo server."""

import calendar
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


def bucket(beginning, receipts, demand, safety):
    planned = max(0, demand + safety - beginning - receipts)
    return planned, beginning + receipts + planned - demand
