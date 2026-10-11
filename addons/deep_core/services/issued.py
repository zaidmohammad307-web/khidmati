"""Read cumulative component issues from native move genealogy."""


def net_issued(raw):
    raw.ensure_one()
    incoming = raw.move_orig_ids.filtered(
        lambda move: move.state == "done" and move.location_dest_id == raw.location_id
    )
    quantity = sum(
        move.product_uom._compute_quantity(move.quantity, raw.product_uom) for move in incoming
    )
    returns = raw.env["stock.move"].search(
        [
            ("origin_returned_move_id", "in", incoming.ids),
            ("state", "=", "done"),
            ("location_id", "=", raw.location_id.id),
        ]
    )
    quantity -= sum(
        move.product_uom._compute_quantity(move.quantity, raw.product_uom) for move in returns
    )
    return max(0, quantity)
