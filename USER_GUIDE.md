# Operator guide

## Plan and release

Load actual product, supplier, unit, BOM, routing, work-center, inventory and demand data using the templates and import preview. For SAP use the connector guide instead of duplicating procurement/customer sources. Review the planning cockpit and material risk. Calculate an MPS plan, review its shortages/capacity, acknowledge warnings with a reason, approve/firm it, then release. Repeating release does not duplicate MOs. Released demand/revisions are frozen.

A SAP-backed draft plan requires a fresh complete profile and stock for every relevant product/warehouse. Its native manufacturing receipts and SAP open PO lines form incoming supply. A native-only plan continues to use native stock and incoming transfers.

## Department material preparation

Open **Operations → Material kits**. Choose a confirmed MO, department and release capacity. Fill the requirements for the whole MO, request and approve the kit. Stage the actual full requirement from warehouse stock onto this MO's dedicated rack. Complete any native subassembly post-production warehouse receipt first; a completed manufacturing order in a three-step warehouse can still have its goods awaiting transfer to Stock.

Enter each issue quantity for the department's current capacity and post it. Issues use real native transfers with raw-move links; partial issues remain partial and cumulative issues cannot exceed the MO requirement. A missing component or lot blocks the transfer. Set the native MO/current-work quantity producing to the actual batch you are processing. Use another issue when additional capacity is available.

Return only unconsumed issued material, with a reason, to the same MO rack. The system unreserves/reassigns native raw stock and records an actual return transfer. Staged, issued, returned and remaining quantities come from posted moves. The rack does not disappear when a shift report says good units were made.

## Work instructions and shop floor

Approve a dated instruction revision and associate its operations. An operation marked instruction-required must have an effective approved document. On the shop floor choose **Read and acknowledge SOP**. Read each current document and explicitly confirm it. The acknowledgement is tied to the current user, MO work order and document version. A newly effective revision requires a new acknowledgement; old or future revisions do not bypass the gate.

Start the permitted station once actual material and maintenance conditions are satisfied. Finish records native work progress. S09 assigns actual serials within the MO quantity. S12 scans a known serial/QR at the correct test station; answer all mandatory typed checkpoints. A fail/HOLD creates the repair/case flow. The assigned technician documents repair, then the same serial is retested. S13/native receipt releases only eligible passing units. Unfinished units remain WIP and do not increase finished inventory.

## Shifts and handovers

Report a shift's planned, good, rework, scrap and downtime values with notes. A zero-output shift needs a reason. Submit for supervisor approval; approved reports cannot be edited through ordinary RPC. The control tower labels these as **reported** actuals.

Send a WIP handover to a separate designated receiving user. That user verifies quantity/custody and receives it. The sender cannot acknowledge receipt for them. This acknowledgement is separate from any native stock movement required by the warehouse process.

## Maintenance

Create a downtime event with work center, reason, expected end, team and technician. Starting it creates the native maintenance request and calendar leave. Blocking events stop work-order start/completion, including ordinary native state writes. Update the expected end if recovery changes. The assigned technician closes it with evidence and the actual end. Configure preventive plans with equipment/team, next date and interval; dated native requests are created once. The preventive scheduler is deliberately inactive until enabled by the manager.

## Quality and CAPA

A failed scanned test creates a linked nonblocking case alongside its repair flow. QA can create a blocking case for an individual serial or an entire MO. Contain it, record root cause, assign actions, complete actions, review effectiveness, and verify closure. An open blocking case holds release and outbound shipment for the affected scope, including every unit on a held MO. Ordinary users cannot mark it closed by editing state.

## Improvement and revisions

Calculate a what-if scenario from a captured base plan using demand multiplier/date shift/overtime sensitivity. It recalculates real MPS/BOM/calendar data with isolated demand. It is a comparison, cannot release orders, and leaves the base plan unchanged.

For engineering changes clone the proposed BOM/routing into an inactive revision, edit it, document impact/effectivity, submit and obtain manager approval. Applying the approved digest activates it for future selection; existing MOs retain their original BOM. Use the same workflow for a reviewed SAP BOM snapshot. Alternatives are qualified advisory candidates; applying one requires controlled engineering review.

Stock policies use dated actual consumption including zero-consumption days, supplier lead/review time, service factor and native unit rounding. Calculate a proposal and approve it. SAP-mode proposals export for SAP review; native reorder-point creation requires the explicit Odoo procurement mode and an approved proposal.

## Contracts and delivery

Enter a customer contract and product/quantity/due-date milestones. Confirm once to create frozen native firm demand. Avoid duplicating an already imported SAP sales order. Complete any native post-production transfer into the shipping stock location first. Create a native delivery for eligible finished stock and validate its actual transfer/serials. Delivery/remaining counts come from done native moves; a prepared picking does not count as shipped. Native customer returns reduce delivered quantities. Overdelivery, held/nonreleased units and insufficient actual serialized source stock are blocked. Close only when milestones are fully delivered. A closed contract is history; replacement deliveries after a later return need an explicit amendment.

## Control tower

Use Overview to open attention records and export actions. The other tabs show actual rack queues, dispatch, approved shift reports, open breakdowns, quality cases and delivery milestones. **Open** takes you to the native record; **Open full list** provides all records, saved filters and native search. Optional live refresh runs every 30 seconds while visible. SAP connection status appears alongside operational exceptions. Time/date inputs use the user's Odoo timezone; the footer labels its server refresh timestamp as UTC. Set operational users to Asia/Amman.

The supplied screenshots use lab records. They show real screens and do not imply your SAP endpoint or live production data is connected.
