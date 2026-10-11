# Deep Elements Manufacturing — complete Odoo 19 source

A single installable application with **16 custom add-ons**, native Odoo Community manufacturing/inventory, Python backend services, OWL frontend screens, SAP Business One Service Layer integration, and a secure deployment profile. All implemented modules ship together.

Start with [INSTALLATION.md](INSTALLATION.md), then [USER_GUIDE.md](USER_GUIDE.md). For your local SAP server through VPN, use [docs/SAP_B1.md](docs/SAP_B1.md). Security and encryption setup is in [docs/SECURITY.md](docs/SECURITY.md). [docs/FEATURES.md](docs/FEATURES.md) describes the implemented scope; [docs/VERIFICATION.md](docs/VERIFICATION.md) records what was actually tested.

## Included

- Firm/project/forecast demand, MPS, multilevel native BOM explosion, shortage and capacity views, frozen approvals, explicit idempotent MO release, and XLSX exports.
- Frame, motor and electronics subassemblies; a 13-station final assembly flow; per-unit S09 serialization; S12 scanned typed QA; same-serial repair/retest; S13 release and native finished-stock receipts.
- Whole-MO material kits on dedicated racks, department capacity limits, actual native issues/returns, separate receiving acknowledgements and approved shift actuals.
- Work instruction versions and acknowledgements; blocking downtime linked to native maintenance/calendar leaves; preventive maintenance; nonconformance/CAPA; controlled BOM revisions; isolated what-if plans; qualified alternatives; statistical stock policies; customer delivery milestones and native returns.
- Responsive operations control tower with attention queues, native record navigation, live refresh, action-list export and serial WIP zones.
- SAP B1 items, partners, warehouse stock, open POs, customer demand and optional BOM snapshots. Atomic refresh, bounded retries, mapping checks, stale-data gates, reviewed BOM import and verified native count reconciliation.
- HTTPS, verified PostgreSQL/SAP TLS, native TOTP MFA support, 30-minute session inactivity, manufacturing roles/company isolation, protected workflow transitions and audit history. AES-256-GCM encrypted backups. Live database/filestore/key encryption requires an encrypted host disk as described in the security guide.

## Source structure

`addons/` contains all backend models/services/wizards, access rules, XML views and OWL JS/XML/SCSS. `runtime/` contains the upstream Odoo launcher and database bootstrap. `scripts/` contains setup, lifecycle, authenticated backup/restore and verification commands. `config/` and Compose files contain deployment configuration. `data/import_templates/` contains all CSV templates. `tests/` and add-on `tests/` contain standalone and native integration tests. `docs/screenshots/` contains real application captures and the flow image.

The SAP/VPN endpoint, credentials, certificate trust and host disk encryption cannot be verified without your server configuration. No real SAP transaction was sent during development. The connector exposes approved read datasets; it does not create SAP purchase orders, invoices, payments or stock postings.

The archive includes `source-history.bundle`. Recover the repository with `git clone source-history.bundle drone-odoo-history`. Upstream Odoo source and dependencies are installed by the pinned official container image; they are not replaced with local substitutes.
