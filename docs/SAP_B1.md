# SAP Business One over VPN

## Connection topology

The Odoo **backend** reaches the SAP Service Layer HTTPS hostname through the VPN route on its host. The browser only talks to Odoo. SAP credentials are never sent to frontend code or stored in an Odoo connection record.

A URL such as `https://sap-vpn.example.internal:50000/b1s/v2` is illustrative. Use your actual Service Layer listener/port and a hostname listed in its certificate. `/b1s/v2` is the OData v4 endpoint; the connector also supports the legacy `/b1s/v1` response pagination format. A VPN by itself does not enable Service Layer or make a localhost-only listener remotely reachable.

**Container localhost means the Odoo container.** If SAP runs on the same host, `host.docker.internal` is mapped by Compose, but it must also appear on the SAP certificate to be a valid TLS hostname. If SAP is on a remote VPN host, use that host's VPN DNS name/private address and certificate. With Docker Desktop, verify that the VPN routes container traffic; a connection from a host browser alone does not prove this.

## Configure once

1. On the SAP server, verify that Service Layer is installed for the actual SAP B1 version/database platform and listening on the private/VPN interface. Restrict its firewall to the integration host. Obtain its CA certificate and the permitted entity list from your SAP administrator.
2. In private `.env` set `SAP_B1_BASE_URL`, `SAP_B1_COMPANY_DB`, `SAP_B1_USERNAME`, and optionally `SAP_B1_CA_BUNDLE=/mnt/sap-ca/sap-ca.pem`. Copy only the public SAP CA chain to `certificates/sap-ca.pem` and make that public file readable by the Odoo container (0644 on Linux).
3. Put the integration password in `secrets/sap-password.txt` locally, without quotes, using a private editor/secret manager. Preserve owner-only host permissions. Do not paste it in chat, put it in the source tree, or use it in a URL. The default secure storage initializer copies this one secret into an owner-only Odoo-readable file on the encrypted data volume. It does not mount the backup key or local CA signing key into Odoo.
4. For changed credentials, run `docker compose run --rm --no-deps storage-init`, then `docker compose up -d --force-recreate odoo gateway`. This applies the file and environment without modifying business records.
5. Open **Manufacturing → SAP Business One → Connections** as a manager. Create your company profile. Leave URL empty to use the server environment, or enter the approved HTTPS URL. Endpoint overrides must match `SAP_B1_BASE_URL` or an explicit server-only `SAP_B1_ALLOWED_ENDPOINTS` list; a manufacturing manager cannot redirect server credentials to an arbitrary host. The default environment prefix is `SAP_B1`. Separate companies can use distinct prefixes configured on the server.
6. Map each SAP warehouse code to its native warehouse and reconciliation location. Map every SAP inventory unit name to its native UOM and factor. The factor means **native units per SAP inventory unit**. Bound item conversions are frozen; change them only through an explicit migration.
7. **Test VPN connection** performs verified TLS login and an authorized Items read. It records a safe diagnostic, not raw server responses or credentials. Then choose **Refresh SAP data**, inspect the job, and **Run refresh now**. The scheduled runner also processes pending jobs.
8. Review the item/partner bindings, quantities, dates and job counts. Enable automatic refresh only after the first complete refresh. Profiles default to manual; interval defaults to 15 minutes, freshness to 60 minutes, maximum records to 10,000 per dataset. If a limit is exceeded, the job fails rather than apply a partial snapshot.

## Ownership and behavior

| Dataset | Implemented behavior |
| --- | --- |
| Items | Bind unambiguous existing native product codes or create stockable products; require explicit UOM and compatible tracking. Existing prices, native naming, routing and approvals are preserved. |
| Business partners | Bind unique SAP codes to native partner refs or create basic identities. No invoice, payment, bank or accounting synchronization. |
| Warehouse stock | Timestamped on-hand/committed/ordered snapshots by mapped warehouse. A refresh never overwrites native quants. Missing item snapshots become stale. |
| Open purchase orders | Import remaining inventory quantities and due dates. Used as external incoming supply, not native PO copies. Unsupported remaining-quantity fields fail validation. |
| Customer sales orders | One native firm demand per company/profile/DocEntry/LineNum. Repeat refresh is idempotent. Native users cannot edit source-owned lines. SAP changes to reviewed/released demand cause an atomic conflict requiring an explicit planning amendment. Closed source lines remove only unfrozen draft demand; historical released demand remains for traceability. |
| BOMs | Optional snapshots; **Prepare engineering change** clones the existing native routing into an inactive revision. Review component operation assignments, submit, approve and apply. Existing MOs keep the old BOM. No routing is invented from SAP resources. |

Select the SAP profile on a **draft MPS plan** to use its fresh stock/open PO source. The plan retains native manufacturing receipts but excludes native supplier promises so the same PO is not counted twice. Stock uses SAP on-hand; commitments are displayed separately because imported firm demand is netted by MPS. What-if previews retain the same source while isolating scenario demand.

Do not duplicate one SAP customer order as a native contract/manual demand. Replenishment proposals remain in the company's SAP procurement mode unless you deliberately choose native Odoo procurement.

## Native inventory cutover

An aggregate SAP snapshot is not a physical issue/receipt and contains no lot/serial genealogy. For an untracked item, a manager can open **Review native stock count**, verify the physical count, freshness, conversion and cutover reason, then apply a native inventory adjustment. Active transfers, reservations, owners, packages, tracked items, negative counts and stale snapshots are rejected. For lots/serials use a verified native tracked count; the connector does not fabricate identifiers.

Keep manufacturing locations and finished inventory aligned operationally. Odoo's physical issue and serial QA checks continue to use actual native stock even when MPS reads SAP snapshots. No finished-stock receipt, shipment, or SAP business posting is inferred from a refresh. This connector does not write purchase orders, invoices, payments, production orders or stock transactions back to SAP.

## Diagnostics

| Code / condition | Next action |
| --- | --- |
| CONFIG_URL / CONFIG_CREDENTIALS / CONFIG_SECRET | Set the real HTTPS endpoint and private server secret, then restart/recreate the service. |
| VPN_UNREACHABLE | Check container routing, VPN DNS, Service Layer listening address/port and firewall. |
| TLS_CERTIFICATE | Use the correct certificate hostname and mounted CA chain. Verification cannot be disabled. |
| SAP_LOGIN / SAP_PERMISSION | Confirm database, integration account and read authorizations with the SAP administrator. |
| ITEM_UNIT_MAPPING / ITEM_IDENTITY_CONFLICT | Resolve explicit unit mapping, duplicate code, native tracking or conversion migration. |
| FROZEN_DEMAND_CONFLICT | Review source change and create an operational planning amendment; do not overwrite frozen history. |
| RECORD_LIMIT / TIME_BUDGET | Narrow selected datasets, partition the source, or deliberately adjust the record limit. An incomplete refresh is never applied. |

Requests use connect/read deadlines, bounded transient retries, a 90-second elapsed budget checked between requests, same-origin pagination, no HTTP redirects and no generic proxy environment. Known failures are recorded safely. Pending jobs lock profile/mapping edits; cancellation is audited. Automatic jobs retain failure/retry history and are shown in the control tower.

The development verification uses fake Service Layer responses and real Odoo transactions. Your live VPN route, SAP version/schema, account authorization and refresh volume still require a first successful connection on the deployment host.

Primary SAP references: [Service Layer API](https://help.sap.com/doc/056f69366b5345a386bb8149f1700c19/10.0/en-US/Service%20Layer%20API%20Reference.html), [Working with Service Layer](https://help.sap.com/doc/fc2f5477516c404c8bf9ad1315a17238/10.0/en-US/Working_with_SAP_Business_One_Service_Layer.pdf).
