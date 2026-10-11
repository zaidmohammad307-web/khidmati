# Gap analysis and roadmap: MPS / MRP / shop floor with SAP Business One

This document reviews the delivered source against the goal of a complete
MPS + MRP + shop-floor system that works seamlessly with SAP Business One,
and sets out what to build next, in order.

## Where the system stands

The foundation is solid. It runs on native Odoo 19 manufacturing objects
(BOMs, routings, MOs, work orders, stock moves) without patching core. It has
role and company isolation, ordered row locks, idempotency keys, immutable
audit and QA records, and an atomic, read-only SAP Service Layer connector with
careful TLS and secret handling. The 62 standalone tests and the native Odoo
tests pass on a fresh Odoo 19 database.

The biggest gap is not code quality. It is that **SAP never hears what
happens on the shop floor**.

## 1. Critical gap: SAP integration is one-way

The connector only reads Items, Business Partners, warehouse stock, open POs,
Sales Orders and BOMs. Nothing goes back to SAP. In practice that means:

| Shop-floor event in Odoo | What SAP B1 should receive | Today |
| --- | --- | --- |
| MPS releases an MO | Production Order (`ProductionOrders`, OWOR) | nothing |
| Warehouse issues a kit | Issue for Production (`InventoryGenExits`, base type 202) | nothing |
| S13 releases finished drones | Receipt from Production (`InventoryGenEntries`, with serial numbers) | nothing |
| MRP BUY suggestion approved | Purchase Request (`PurchaseRequests`) or draft PO (`Drafts`) | CSV/XLSX export only |
| Kit moved to a rack or line | Inventory Transfer (`StockTransfers`), if the bins live in SAP | nothing |
| Scrap or rework replacement part | Goods Issue with a reason | nothing |

Consequences:

* **Two inventory ledgers drift apart.** Odoo consumes components and
  receives drones; SAP still shows the old stock. A plan using the SAP
  profile then counts stock that has already been consumed on the floor.
* **No costing or accounting.** Work in progress, consumption variance and
  finished-goods value never reach SAP finance.
* **Double keying.** Someone has to re-enter every production order, issue
  and receipt in SAP by hand.

### Decision needed first: who owns inventory?

| Option | Description | When it fits |
| --- | --- | --- |
| **A. SAP owns inventory and finance (recommended)** | Odoo plans and runs the floor. Every physical movement is posted to SAP through an outbox. Odoo stock is an operational mirror, reconciled against SAP every night. | SAP B1 is already the book of record and auditors and accountants work in it. This is the usual pattern. |
| B. Odoo owns WIP; SAP gets summaries | Odoo keeps detailed WIP and stock. SAP receives only finished-goods receipts and periodic consumption summaries. | SAP is used mainly for finance and sales, and the warehouse runs in Odoo. |
| C. SAP owns production orders too | SAP creates Production Orders; Odoo only executes them. | MRP already runs in SAP (not the case here). |

### Recommended design for write-back (option A)

1. **Transactional outbox.** A `deep.sap.outbox` record is written in the
   same database transaction as the Odoo event (MO release, issue, receipt).
   It holds the target entity, a JSON payload, a stable idempotency key, and
   dependency ordering (Production Order before Issue before Receipt).
2. **Idempotent posting.** A user-defined field (`U_DeepRef`) is written on
   every SAP document. Before retrying, the worker queries SAP by `U_DeepRef`,
   so a timeout after SAP committed never creates a duplicate document.
3. **Worker.** A cron job runs the outbox in order, with bounded exponential
   retry. Business errors (closed period, negative stock, missing batch) go to
   a dead-letter state that needs a person to resolve it. Transport errors
   are retried.
4. **Client allow-list.** Extend `ServiceLayerClient` with `create()` and
   `query()` for the write entities above only. Keep the read and write
   allow-lists explicit and separate.
5. **Serial and batch alignment.** Drone serials created at S09 go into the
   SAP receipt's `SerialNumbers` collection. Component batches are read from
   `BatchNumberDetails` so genealogy matches in both systems.
6. **Reconciliation.** A nightly job compares Odoo quants with SAP
   `ItemWarehouseInfoCollection` per mapped warehouse and opens an exception
   for anything outside tolerance.
7. **Operations console.** The control tower shows outbox backlog, oldest
   pending item, dead letters, and the last reconciliation result.

### Other SAP gaps

* **Delta sync.** Every refresh re-reads every item, capped at 10,000 rows
  per dataset. Filter by `UpdateDate`/`UpdateTime` for 15-minute deltas and
  keep a nightly full refresh.
* **Item cost.** `AvgStdPrice` / `ItemPrices` are not read, so there is no
  cost roll-up or variance.
* **SAP Production Orders are not read.** If anyone still creates PdOs in
  SAP, MRP ignores that supply.
* **Resources and routing stages** (SAP B1 10.0) are not mapped to work
  centres.

## 2. MPS / MRP gaps

| Gap | Impact | Status |
| --- | --- | --- |
| Safety stock was a single number per plan, applied to every item | A frame, a motor and a finished drone all got the same buffer | **Fixed in this branch**: per-item `Safety Stock`, with the plan value as default |
| No lot sizing | MOs and buy suggestions were exactly the shortage, ignoring MOQ and pack sizes | **Fixed in this branch**: per-item `Minimum Lot` and `Lot Multiple` at MPS and component level; excess carries forward |
| No rescheduling messages (expedite / defer / cancel existing POs and MOs) | Planners only see new orders, not that an existing PO must be pulled in | Next |
| One MO per requirement row, no consolidation by period | Many small MOs for the same subassembly | Next |
| An item that is both an MPS item (for example a spare frame) and a component has its stock counted in both places | Under-planning of shared subassemblies | Next (fix in `MaterialService._supply`) |
| No available-to-promise (ATP) or capable-to-promise | Sales cannot quote reliable delivery dates | Later |
| Planning per single warehouse | No multi-site or inter-warehouse supply | Later |
| Rough-cut capacity only | No finite sequencing per work centre | Later (finite scheduler or Odoo Enterprise planning) |
| No statistical forecasting from sales history | Forecast demand is entered by hand | Later |
| `filtered()` inside nested loops in `MPSService.calculate` | O(products × buckets × demands); slow with large catalogues | Pre-group demand by product and bucket |

## 3. Shop-floor gaps

* **Station login by badge or PIN** (kiosk mode) instead of a full Odoo
  session per operator.
* **OEE** (availability × performance × quality). Downtime, cycle times
  and QA outcomes are already captured; only the calculation and view are
  missing.
* **Andon / call for help** from a station, routed to supervisor or
  maintenance.
* **Scrap at the station** with reason codes, posted to SAP.
* **Test-equipment calibration** records that block S12 when an instrument
  is out of date.
* **Drone-specific as-built record per serial:** firmware and configuration
  versions, flight-test log, Remote ID or registration data, exportable as a
  device history record.
* **Line-side barcode issue and consumption** in addition to whole-kit issue.
* **Offline tolerance** for stations on unreliable Wi-Fi.

## 4. Engineering practice

| Item | Status |
| --- | --- |
| Lint rules covered only syntax and pyflakes (`E4/E7/E9/F`) | **This branch**: adds import order, bugbear, pyupgrade and comprehension rules, with Odoo-specific exceptions |
| Formatting drift (12 files) | **This branch**: formatted |
| CI ran everything inside one Docker job, so lint errors surfaced only after a full stack build | **This branch**: a fast lint and unit-test job gates the Docker acceptance job |
| No pre-commit hooks, no Dependabot | **This branch**: added |
| None of the 284 user-facing error messages are translatable (`_()` / `self.env._()`); no `.pot` files | Next. Needed for an Arabic UI |
| No server logging (`_logger`) | **This branch**: SAP job runner logs outcome, duration and counts. The rest of the add-ons still need it |
| Native Odoo tests run only through the Docker acceptance job | Later: add a CI job using the official `odoo:19` image with `--test-tags /deep_*` |
| No load test with production-size data | Later: generate around 5,000 items and 50 levels of BOM, and measure calculation time |

## 5. Recommended order of work

1. **Decide inventory ownership** (section 1). Everything else in the SAP
   track depends on it.
2. **Build the SAP outbox and the Production Order write-back,** then Issue
   for Production, then Receipt from Production with serials. Test against an
   SAP B1 test company, never production.
3. **Run a nightly stock reconciliation** and show its exceptions in the
   control tower.
4. **Fix the remaining MRP gaps:** rescheduling messages, MO consolidation,
   and the shared-subassembly stock bug.
5. **Make the UI translatable** and ship Arabic if the floor needs it.
6. **Shop-floor upgrades:** badge login, OEE, calibration gates, as-built
   record.
7. **Delta sync and cost** from SAP.
8. **Run a pilot on one product line** in parallel with the current process
   for 2 to 4 weeks, comparing SAP and Odoo stock every day before cutover.
