# Verification · complete application

Verified on 2026-10-11 using official Odoo 19.0-20260926 source/distribution,
Python 3.12, native PostgreSQL 16.15 and Chromium 140 / Playwright 1.55.1.
The project source does not include the downloaded upstream runtime or the
scratch-only environment adapters used to execute it in this preparation host.

| Check | Result |
|---|---|
| Complete fresh database install | PASS: all nine addons and native dependencies; 75 modules; clean shutdown |
| Native upgrade / XML loading | PASS: all nine addons, current model schema, ACLs, rules and inherited views |
| Standalone tests | PASS: 40; lifecycle/environment/backup integrity plus MPS/capacity/typed QA calculations |
| Native Odoo transactional tests | PASS: 10; zero failures/errors |
| Authenticated Chromium frontend | PASS: real cockpit, MPS matrix, shop floor, server scan and typed quality form; zero page errors |
| Native dump/restore roundtrip | PASS: restored to a new database; unit/QA/stock/attachment counts equal; every filestore file byte-equal |
| Python lint/format | PASS: Ruff E4/E7/E9/F; 100-column formatting |
| Frontend formatting | PASS: Prettier JavaScript/SCSS |
| XML/schema validation | PASS: real Odoo module loader; structured XML source |

## Native workflow coverage

1. Idempotent S9 serialization, initial PASS/FAIL, automatic repair, assigned
   diagnosis/repair, same-serial retest PASS, immutable results, recorded actual
   consumption, S12/S13 completion and native serial finished receipt.
2. Mixed good/held units: partial good release, native MO backorder, held unit
   re-associated with the backorder and excluded from finished stock.
3. Planned 60 / actual warehouse issue 10: issued 10, consumed 0, remaining 50.
4. Firm 60 / forecast 100 with 50% confidence: nominal 100 / weighted 60;
   acknowledged warnings, review/approve/firm, idempotent native MPS release.
5. Import dry-run rollback, approved atomic apply, retry safety, duplicate rejection
   and no first-row partial commit when a later row is invalid.
6. Operator cannot modify protected BOMs or forge service capability using RPC context.
7. Wrong station, missing mandatory results and premature S13 fail; original tester
   can rescan and resume a draft test.
8. Recursive demand releases one native final MO and three real subassembly MOs,
   each with its own native BOM/routing/work orders and parent link.
9. Company-scoped operator cannot read another company's family record.
10. Edited draft demand invalidates calculation; stale review and reviewed input
    edits are rejected until an appropriate revision/recalculation.

Native transactional tests roll their test records back. Browser screenshot
records are separate lab data; screenshots are real app captures rather than
mockups. `00-concept-flow.png` is the earlier conceptual illustration, while
01–04 show native Odoo/OWL rendering. Evidence extracts are in `docs/evidence/`.

## Remaining deployment validation

This host has no Docker engine. Docker image build, Compose startup/health orchestration,
container backup/restore wrapper, Windows Docker Desktop and GitHub Actions were
not executed here. The CI workflow runs full Compose install/authentication, native
acceptance and backup/restore to a new database. The native PostgreSQL roundtrip
checks data/filestore integrity but is not a substitute for testing the Docker wrapper.

PDF label printing through the Docker image's wkhtmltopdf, physical scanner/printer
hardware, external SAP integration and organizational provisioning require target
installation verification. No production scale/load benchmark, offline sync,
live SAP connector or finite scheduling optimizer is claimed. Verify TLS/proxy,
worker sizing, real BOMs/routings, labor calendars and approved product test points
on the deployment that will operate the factory.

## Reproduce

```sh
python scripts/manage.py setup
python scripts/manage.py start
python scripts/manage.py test
python scripts/manage.py verify
python scripts/manage.py acceptance
python scripts/manage.py backup --output backups/acceptance.zip
python scripts/manage.py restore backups/acceptance.zip --target acceptance_restore --activate
python scripts/manage.py verify
```

Run acceptance in a dedicated demo-enabled pilot. Preserve the original database
and a checked backup before upgrading an operational installation.
