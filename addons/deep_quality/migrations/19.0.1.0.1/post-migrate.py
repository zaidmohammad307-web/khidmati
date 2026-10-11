"""History indexes for installations upgraded from 19.0.1.0.0. No stock data is rewritten."""


def migrate(cr, version):
    cr.execute(
        "CREATE INDEX IF NOT EXISTS deep_quality_session_unit_history ON deep_quality_session (unit_id, id DESC)"
    )
    cr.execute(
        "CREATE INDEX IF NOT EXISTS deep_quality_session_company_outcome ON deep_quality_session (company_id, outcome, ended_at) WHERE state='done'"
    )
