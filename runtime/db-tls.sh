#!/bin/sh
set -eu
# Root-owned read-only secret mounts are copied with PostgreSQL's required key ownership.
install -d -m 700 -o postgres -g postgres /var/lib/postgresql/tls
install -m 600 -o postgres -g postgres /run/tls/db.key /var/lib/postgresql/tls/server.key
install -m 644 -o postgres -g postgres /run/tls/db.crt /var/lib/postgresql/tls/server.crt
# Enforce TLS on TCP for both new and existing databases. Local Unix sockets remain available for maintenance.
if [ -f "$PGDATA/pg_hba.conf" ] && ! grep -q 'DEEP_TLS_REQUIRED' "$PGDATA/pg_hba.conf"; then
  { printf '# DEEP_TLS_REQUIRED\nhostnossl all all 0.0.0.0/0 reject\nhostnossl all all ::/0 reject\n'; cat "$PGDATA/pg_hba.conf"; } > "$PGDATA/pg_hba.conf.secure"
  chown postgres:postgres "$PGDATA/pg_hba.conf.secure"
  chmod 600 "$PGDATA/pg_hba.conf.secure"
  mv "$PGDATA/pg_hba.conf.secure" "$PGDATA/pg_hba.conf"
fi
exec docker-entrypoint.sh postgres -c ssl=on -c ssl_min_protocol_version=TLSv1.2 \
  -c ssl_cert_file=/var/lib/postgresql/tls/server.crt \
  -c ssl_key_file=/var/lib/postgresql/tls/server.key
