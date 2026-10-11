"""Server-side capabilities cannot be forged using an RPC context scalar."""

from odoo.exceptions import AccessError

_CAPABILITY = object()


def internal(records):
    return records.with_context(_deep_capability=_CAPABILITY)


def require_internal(env):
    if env.context.get("_deep_capability") is not _CAPABILITY:
        raise AccessError("Use the validated workflow action.")


def require_role(env, *roles):
    if not env.su and not any(env.user.has_group("deep_core.group_" + r) for r in roles):
        raise AccessError("Your manufacturing role does not permit this action.")


def lock(records):
    records.check_access("write")
    if records:
        records.env.cr.execute(
            f'SELECT id FROM "{records._table}" WHERE id = ANY(%s) ORDER BY id FOR UPDATE',
            [sorted(records.ids)],
        )
        records.invalidate_recordset()
