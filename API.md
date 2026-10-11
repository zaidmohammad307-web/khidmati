# API and service boundaries

The frontend uses authenticated Odoo session JSON-RPC `/web/dataset/call_kw/<model>/<method>`. Requests include `model`, `method`, `args` and `kwargs`; native CSRF/session/access controls and ORM transactions apply. There is no separate unauthenticated scanner API or invented REST stock endpoint.

| Model / public method | Arguments | Result |
|---|---|---|
| `deep.manufacturing.dashboard.metrics` | `[]` | Current company cockpit metrics/matrix/schedule |
| `deep.shopfloor.board` | `[offset]` | Up to 50 current open MOs with stations, units and actual material status |
| `deep.shopfloor.station_action` | `[workorder_id, action, quantity, request_key]` | Native start/finish action or serialized unit IDs |
| `mrp.workorder.action_deep_serialize` | `[[workorder_id], quantity, request_key]` | Stable unit IDs; idempotent key scoped to MO |
| `deep.quality.session.action_scan` | `[serial, workorder_id, request_key]` | Session ID, serial, template/version and typed point definitions |
| `deep.quality.session.action_submit` | `[[session_id], answers, notes, hold]` | Serial/outcome; immutable answers and rework action in same transaction |
| `deep.shopfloor.release` | `[unit_ids]` | Native MO completion action/wizard |
| `deep.shopfloor.print_labels` | `[unit_ids]` | Native QWeb label report action |
| `deep.mps.plan.action_calculate/review/approve/firm/release` | `[[plan_id]]` | Validated state transition |
| `deep.import.batch.action_validate/approve/apply` | `[[batch_id]]` | Validated dry-run/approval/atomic import |
| `deep.material.risk.action_refresh` | `[]` | Current-company risk snapshot window |

Example QA answers:

```json
[
  {"point_id": 101, "value": true},
  {"point_id": 102, "value": 15.4},
  {"point_id": 103, "value": "Inspection note"}
]
```

Numeric values must be finite numbers; boolean/pass-fail values must be real JSON booleans. Text/selection values are strings; selection must match a configured option. Missing mandatory, duplicate or unrelated point IDs are rejected. HOLD requires a reason. Only the initiating tester may submit. Scans and serial generation require 8–100 character alphanumeric/underscore/hyphen keys; the frontend uses UUIDs and retains keys across failed requests.

Core private services: `SerializationService`, `MPSService`, `MaterialService`, capacity computation, `QualityService`, `ReworkService`, `ImportService`. Private Python capability context cannot be forged through JSON-RPC. SQL locks and native constraints protect state-changing actions. UI buttons do not confer authority.

Native `/report/barcode/QR/<serial>` serves QR images and QWeb reports serve labels. Native attachments carry XLSX exports; export generation disables formula/URL interpretation. RPC services expose only company/role-authorized records; use normal native Odoo authentication rather than sharing an administrator session in a scanner station.
