# SQL boundary

Native Odoo creates application tables from model definitions. Runtime PostgreSQL
role setup is in `runtime/init-db.sh`. Custom SQL is scoped to:

- Ordered row locks in `deep_core/security.py` for workflow serialization.
- Declarative native ORM constraints and indexes.
- Read-only quality analytics in `deep_manufacturing_dashboard/models/reporting.py`.
- History indexes in `deep_quality/models/session.py` and its versioned migration.

Stock quantities, manufacturing completion, QA history and demo transactions use
native ORM/services. No SQL stock ledger, direct balance rewrite or historical
PASS backfill is provided. See DATABASE.md.
