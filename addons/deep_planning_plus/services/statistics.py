"""Transparent replenishment math, separate from Odoo and stock posting."""

import math
import statistics


def reorder_policy(daily, lead, coverage, z_score, rounding=1):
    if not daily or any(not math.isfinite(value) or value < 0 for value in daily):
        raise ValueError(
            "Daily consumption must be a nonempty series of finite nonnegative values."
        )
    if (
        any(not math.isfinite(value) for value in (lead, coverage, z_score, rounding))
        or lead < 0
        or coverage <= 0
        or z_score < 0
        or rounding <= 0
    ):
        raise ValueError("Invalid policy inputs.")
    mean = statistics.fmean(daily)
    std = statistics.pstdev(daily)

    def round_up(quantity):
        return math.ceil(quantity / rounding - 1e-9) * rounding

    safety = round_up(z_score * std * math.sqrt(lead))
    reorder = round_up(mean * lead + safety)
    maximum = max(reorder, round_up(mean * (lead + coverage) + safety))
    return {
        "daily_mean": mean,
        "daily_std": std,
        "safety_qty": safety,
        "reorder_qty": reorder,
        "maximum_qty": maximum,
    }
