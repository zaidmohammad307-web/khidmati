# Install the complete application

## Requirements

Use Python 3.12+, Docker Engine/Desktop with **Compose 2.24.4 or newer**, and an encrypted disk or mount for the project, secrets and Docker persistent storage. Allow enough storage for PostgreSQL, Odoo and backups. Use a separate SAP integration account with read access to the selected Service Layer entities.

The container images are pinned in `.env.example`. The host tools use `scripts/requirements.txt`. No credentials are shipped.

## New installation

1. Extract the full project onto the encrypted host disk. On Windows, check BitLocker for the drive containing both the project and Docker Desktop's virtual disk. On Linux, use an existing LUKS encrypted volume; do not format an occupied disk. See `docs/SECURITY.md`.
2. Install the host tool dependencies:
   ```sh
   python -m pip install -r scripts/requirements.txt
   python scripts/manage.py setup
   ```
   Setup creates four different passwords, a random backup key, an empty SAP secret placeholder, and a local CA/server certificate set. Repeating setup preserves them.
3. Edit `.env` privately. Set `DEEP_ENCRYPTED_DATA_DIR` to an absolute directory on your encrypted storage. Use forward slashes on Windows, for example `D:/DeepData`. Set `DEEP_HOSTNAME` to the certificate's hostname. `localhost` is the generated default. Keep `COMPOSE_FILE=docker-compose.yml:docker-compose.secure.yml` and `COMPOSE_PATH_SEPARATOR=:`.
4. Trust the **public** `secrets/ca.crt` on every device that opens the application. Never copy `ca.key`, `web.key`, `db.key` or `backup.key` into a browser. The certificate setup and renewal instructions are in `docs/SECURITY.md`.
5. Run:
   ```sh
   python scripts/manage.py check
   python scripts/manage.py start
   ```
   Open `https://localhost:8443/web/login`. Read the generated administrator credentials locally from `.env`. Change the administrator password, create named role-specific users, enable native two-factor authentication and store recovery codes offline.

The first run creates the application role, initializes all 16 custom add-ons and dependencies, and waits for a healthy application. Existing database/users are preserved by repeat starts. Only HTTPS is published by the secure profile. PostgreSQL has no host port. The proxy shares Odoo's namespace; its short HTTP hop stays on loopback. Database TCP traffic requires TLS and Odoo verifies the server CA and hostname.

For access by other VPN devices, choose a VPN DNS hostname before generating certificates, and set `DEEP_BIND_ADDRESS` to the host's VPN interface address. Use the hostname on the certificate. Limit host firewall access to the intended VPN clients. Do not expose Odoo's internal port 8069.

## Upgrade an existing supplied project

Back up the old database/filestore before replacing source. Keep the old `.env`, secrets and persistent data. `setup` merges new defaults while preserving existing credentials; deliberately change `ODOO_BOOTSTRAP_MODULES` to `base,web,mrp,purchase_stock,hr,deep_sap_b1` if your old value ends at the dashboard/control tower. Back up any old Docker named volumes before migrating to the encrypted bind directories; changing a volume path does not copy its contents.

Update all custom modules once:

```sh
python scripts/manage.py update deep_core,deep_mps,deep_capacity_planning,deep_quality,deep_rework,deep_data_import,deep_material_risk,deep_shopfloor,deep_manufacturing_dashboard,deep_operations,deep_maintenance,deep_planning_plus,deep_quality_plus,deep_contracts,deep_control_tower,deep_sap_b1
python scripts/manage.py acceptance
```

For a genuinely new database set `DEEP_DEMO_ENABLED=1` only for a demonstration installation. Set it to `0` for production before initial installation. Switching it later does not delete already-created demo records. The demonstration data is not an operational forecast or approved production dataset.

## Backups and restore

```sh
python scripts/manage.py backup
python scripts/manage.py restore backups/example.deepenc --target deep_restore --activate
```

Backups stop application/cron writes, pair a native PostgreSQL dump with the matching filestore, validate hashes and paths, and encrypt the complete payload with AES-256-GCM. Restore authenticates before database actions and only permits a new database. Keep the backup key in a separate encrypted/offline recovery location. Losing it makes these backups unrecoverable. Test restoration routinely.

Older plaintext archives require the deliberate migration option `--allow-plain-backup`; new backups are always encrypted regardless of the chosen filename extension. Working files are private and placed under `DEEP_ENCRYPTED_DATA_DIR/backup-work`.

## Commands

`setup`, `check`, `start`, `init`, `status`, `logs`, `stop`, `verify`, `test`, `acceptance`, `update`, `backup`, and `restore` are in `scripts/manage.py`. Stop preserves data. Never use `docker compose down -v` on the live system. Run standalone tests after installing the host requirements.

`verify` performs real authentication and API checks using the trusted CA. Once MFA is enabled on that administrator, unattended password-only verification will correctly fail; use browser validation with your second factor. Do not disable MFA to keep a smoke-test password working.
