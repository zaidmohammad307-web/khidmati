#!/usr/bin/env bash
set -euo pipefail

# psql reads secrets from environment, not command arguments or string interpolation.
# This runs only when the official PostgreSQL image creates a fresh data volume.
if [[ ! "${ODOO_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ ]] || [[ "${ODOO_DB_USER}" == "postgres" ]]; then
    echo "ODOO_DB_USER must identify a separate lowercase application role." >&2
    exit 1
fi

psql --set=ON_ERROR_STOP=1 --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" <<'SQL'
\getenv app_user ODOO_DB_USER
\getenv app_password ODOO_DB_PASSWORD
SELECT format(
  'CREATE ROLE %I WITH LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION PASSWORD %L',
  :'app_user', :'app_password'
) \gexec
SQL

if [[ "${DEEP_REQUIRE_DB_TLS:-0}" == "1" ]]; then
    { printf '# DEEP_TLS_REQUIRED\nhostnossl all all 0.0.0.0/0 reject\nhostnossl all all ::/0 reject\n'; cat "$PGDATA/pg_hba.conf"; } > "$PGDATA/pg_hba.conf.secure"
    chmod 600 "$PGDATA/pg_hba.conf.secure"
    mv "$PGDATA/pg_hba.conf.secure" "$PGDATA/pg_hba.conf"
fi
