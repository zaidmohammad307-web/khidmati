# Verification of this source release

Verified on 2026-10-11 using the official Odoo 19.0-20260926 Debian package, native PostgreSQL 16.15, a Python 3.12 runtime and the source add-ons. The host encryption tools use Cryptography 50.0.1; the unchanged native Odoo dependency set comes from the pinned upstream requirements. The code does not patch the upstream Odoo sources.

| Check | Observed result |
| --- | --- |
| Standalone configuration, bootstrap, planning/statistics, backup integrity, encryption and SAP transport tests | **62 tests passed**. Includes wrong-key/tamper/truncation rejection, endpoint credential binding, trusted TLS configuration, session retries and bounded pagination. |
| Native Odoo workflow acceptance | **35 transactional test methods passed**, zero failures/errors. Ten original manufacturing flows, sixteen expanded operational flows, nine SAP flows. |
| Fresh database installation | All **16 custom add-ons** and their dependencies install; **85 total Odoo modules** load. |
| HTTPS browser/API/database flow | Nine new desktop/mobile screenshots; real authentication, Secure/HttpOnly/Lax cookie, HSTS/nosniff, database manager blocked, XLSX export, native record navigation, connector diagnostic, work-instruction modal and persisted acting-user acknowledgement, and calculated scenario view. **Zero page/API errors** in the completed run. |
| Database TLS and encrypted recovery | Real `verify-full` PostgreSQL connection, non-TLS connection rejected, encrypted native dump/filestore backup, restore to a separate database and native row comparison. Original database preserved. |
| Deployment configuration | Merged secure Compose configuration validates with Compose 2.39.4; only gateway TLS port published, no DB port, Odoo on loopback, verified DB TLS, bind paths and storage initializer checked. Caddy 2.11.7 configuration validates. |
| Source style | Ruff lint and formatting pass. |

The native tests cover multilevel MO release/idempotence, frozen demand, warehouse issue/consumption, S09 serialization, mandatory S12 answers, fail/repair/retest, partial receipts and company/role protections. They also cover MO racks/capacity/returns, independent handovers, shift immutability, current-version SOP acknowledgement, downtime and calendar interruption, preventive request idempotence, what-if isolation, approved ECO freezing, SAP-mode reorder policy, CAPA closure, actual contract deliveries and stock guards. A hold on a whole MO blocks every affected unit and outbound shipment. A second generic shipment of an already-shipped serial is rejected for insufficient actual stock.

SAP tests use fake Service Layer responses against **real native Odoo records and transactions**. They verify repeat-safe master/demand binding, remaining PO supply, no duplicated native supplier promise, inherited scenario source, atomic rollback on missing UOM or frozen demand conflict, stale-data rejection, retry/configuration locks, native verified inventory counts, inactive BOM review and cross-company ACLs. They do not contact a real SAP company.

The secure browser check uses a real generated lab CA and verified HTTPS, not a certificate-bypass switch. Native PostgreSQL dump/restore uses the supplied backup functions through a local native command adapter. Docker configuration was parsed and inspected, but a Docker engine was not available to execute the composed containers here. The included CI workflow exercises the actual composed services on a Docker-capable runner; its ephemeral test storage does not verify production disk encryption.

No live SAP/VPN endpoint, credentials, target-host disk encryption, enrolled operator MFA or production-scale load test was available. These remain deployment commissioning checks. Installing native TOTP support is not the same as enrolling users. Code inspection and tests do not establish an absolute security guarantee.

Evidence is in `docs/evidence/`. All 13 application screenshot files use demonstration data. Files 01–04 preserve the earlier core screens; 05–13 capture the current expanded application. `14-complete-flow.svg` and `.png` are a precise rendered flow image; `00-concept-flow.png` is the earlier illustration.

Run `python scripts/manage.py test` after installing `scripts/requirements.txt`, and `python scripts/manage.py acceptance` on the initialized Compose installation. Review the installation/security guides before deployment.
