# Implemented feature map

| Add-on | Backend and frontend responsibilities |
| --- | --- |
| deep_core | Company-isolated demand/production foundation, native material issue/consumption, serial unit genealogy, private workflow capabilities and audit history. |
| deep_mps | Time-bucket MPS, firm/forecast/manual demand, multilevel material ledger, frozen approvals, idempotent native multilevel MO release and XLSX. |
| deep_capacity_planning | Native work calendars, BOM routing setup/cycle load, required/available hours and overload views. |
| deep_quality | Mandatory typed pass/fail/range answers, authorized station scans, idempotent scan sessions and immutable test results. |
| deep_rework | Failed-unit repair routing, assigned technician evidence, same-serial retest and release gates. |
| deep_data_import | CSV templates and native import preview/validation with atomic application. |
| deep_material_risk | Procurement/shortage risk and SAP/Odoo company procurement mode. |
| deep_shopfloor | OWL station cards, material status, start/finish actions, instructions, serialization, QR scan and QA/rework views. |
| deep_manufacturing_dashboard | Planning cockpit, MPS/capacity charts, drill-downs and native demonstration fixtures. |
| deep_operations | Department queues; whole-MO racks; native staging/partial issues/returns; capacity checks; dual handover acknowledgement; submitted shift reports; versioned SOPs and actor acknowledgements. |
| deep_maintenance | Reason-coded downtime, native maintenance requests, work-center calendar interruption, start/finish blocking, technician closure evidence and dated preventive requests. |
| deep_planning_plus | Isolated calculated what-if scenarios, controlled BOM/routing revisions, qualified substitution advice and consumption-based safety/reorder proposals. |
| deep_quality_plus | NC containment/root cause/actions/effectiveness closure; QA failure-linked cases; optional MO/serial blocking release and shipment gates; actual-source serialized stock checks prevent duplicate/negative shipments. |
| deep_contracts | Confirmed customer delivery milestones, idempotent firm demand, native deliveries/returns, remaining quantity and completion checks. |
| deep_control_tower | Responsive OWL overview, attention queue, rack/dispatch/shift/maintenance/quality/delivery tabs, native forms, live refresh and formula-safe XLSX action list. |
| deep_sap_b1 | Service Layer transport, secret-file/TLS configuration, diagnostics, atomic jobs/retries, warehouse/UOM mappings, source-owned demand, planning supply hooks, stock reconciliation and BOM review. |

The scope is the implemented manufacturing operation, not every ERP feature. Accounting, payments, payroll, automatic AI decisions, SAP transactional writeback, native remote VPN establishment, generic attachment malware scanning and enterprise infrastructure monitoring are not implemented here. Use the native ERP/platform controls appropriate to those activities.

The safeguards are enforced in backend methods and native move hooks, not only disabled buttons. Shift good quantities are self-reported operational actuals; finished inventory comes only from eligible serial/native receipts. WIP handovers acknowledge custody; they do not manufacture finished stock. Scenario plans cannot release operational orders. Alternative components remain advice until a controlled BOM revision is approved.
