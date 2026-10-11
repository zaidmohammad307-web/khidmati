import math


def operation_minutes(quantity, cycle, capacity, efficiency, setup, cleanup, batch_size=0):
    values = (quantity, cycle, capacity, efficiency, setup, cleanup, batch_size)
    if (
        not all(math.isfinite(v) for v in values)
        or min(values) < 0
        or capacity == 0
        or efficiency == 0
    ):
        raise ValueError("Invalid capacity parameters.")
    if quantity == 0:
        return 0
    batches = math.ceil(quantity / batch_size) if batch_size else 1
    return batches * (setup + cleanup) + math.ceil(quantity / capacity) * cycle * 100 / efficiency
