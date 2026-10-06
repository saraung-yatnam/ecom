# Product returns — feature progress

Status: implemented and automated release verification complete (2026-10-05).

## Scope and inspected extension points

This feature adds a delivered-product, item/quantity-level return lifecycle.
The completed F01–F20 record remains in `engineering-remediation-progress.md`.

| Existing extension | Feature use |
| --- | --- |
| `Order`, `OrderItem`, purchase snapshots; `get_order_by_id(for_update=True)` | Ownership, delivered eligibility, immutable purchased quantities/prices, order-first serialization |
| `Refund`, `request_admin_refund`, `approve_refund`, provider recovery | One existing money ledger/provider path, role ceilings, four-eyes approval, stable retry keys |
| `apply_refund_state`, refund webhooks/reconciliation | Synchronize linked return completion/failure from actual ledger/provider state |
| Current auth, `require_perm`, DB permission checks | Customer ownership; `orders.view`, `orders.update`, `shipping.manage`, `orders.refund` admin gates |
| `audit.log` | Append-only return events and admin audit in the same mutation transaction |
| PIL/local image upload; public `/uploads` mount | Reuse decoder/local-file approach, but private evidence is outside the public mount and always re-encoded |
| Shiprocket service/auth/client, `get_tracking`, normalization, authenticated webhook | Official separate reverse creation/AWB, reference recovery, manual fallback and shared return tracking |
| Customer `OrderDetail`; admin `AppRoutes`, `Sidebar`, order/refund pages | Separate return panel and permission-gated return list/detail routes |
| Existing pytest/HTTP/RBAC fixtures, Node utility tests, release script | Feature regressions plus full locked release verification |

## Isolated policy

Environment-backed return settings are separate from cancellation/store fee
settings. They expose enablement, optional return window, excluded variant IDs,
reason-specific required evidence, attachment count/size and a return fee percent.
Defaults impose no invented return-window/product exclusions or mandatory photos;
the return fee defaults to zero. Eligibility responses communicate the effective
policy. A configured window requires a recorded delivery timestamp and fails
closed if the timestamp is unavailable.

Refund allocation is isolated in the return service: purchased merchandise value
after proportional order discount/tax, excluding outbound shipping and COD fees.
Integer-cent allocation and per-item remaining value/quantity reservations prevent
rounding overpayments across multiple requests. The request captures its amounts
and fee; later policy changes cannot change an approved return's captured quote.
Original cancellation fee calculations remain intact.

Delivered, paid online orders and explicitly collected COD orders can request
returns. COD has no online provider refund: an authorized admin records an actual
manual repayment reference through the existing refund ledger/authority pipeline;
this records repayment and never pretends to send cash through a PSP. Uncollected
COD cannot enter this money-return workflow.

## Schema and lifecycle

Add `return_requests`, `return_items`, `return_evidence`, `return_events` and
nullable return/manual-transfer fields on the existing `refunds` ledger. Requests
link customer/order, reserve purchased item quantities, capture one reason/detail
for the selected items and carry timestamps, decisions, tracking and inspection.
The migration follows `u6c7d8e9f0a1`, adds constraints/indexes/FKs, and does not
rewrite existing rows.

States: `requested`, `approved`, `rejected`, `return_shipped`, `received`,
`inspection`, `refund_pending`, `refunded`, `cancelled`.

- Submission is atomic with attachments; an owner-scoped idempotency key replays
  the identical payload and rejects a changed payload. Order-first locks serialize
  all quantity reservations; rejected/cancelled requests release quantities.
- Requested → approved/rejected/cancelled. Approved → return_shipped/received/
  cancelled. Only admins confirm receipt/inspection; customers may cancel before
  shipping and attach manual tracking to approved requests.
- Received → inspection. Inspection captures an explicit pass/fail and public
  note. A passed inspection is required before any refund request or approval.
- Refund pending means either second-admin approval or accepted provider money
  in flight. Only provider completed status (or recorded COD repayment) means
  refunded. Failed/rejected money attempts return to inspection for an explicit
  retry without releasing physical returned quantities.
- Courier delivery can advance an attached return to received only. It cannot
  pass inspection, restock inventory, or authorize/refund money. Terminal/late/
  duplicate scans cannot regress the return.
- No automatic restocking is introduced: damaged/defective returns require
  separate inventory disposition policy. The whole-order cancellation/RTO stock
  release guard is not used for item returns.

All admin mutations check DB permissions in service boundaries as well as router
dependencies. Customer reads/uploads/downloads require ownership. Evidence is
bounded JPEG/PNG/WebP input decoded with PIL, pixel-limited, then re-encoded to
sanitized JPEG with metadata/trailing bytes discarded. Private download endpoints
return no-store/nosniff responses; filenames/storage keys are never public URLs.
Failed file/DB transactions remove only newly written evidence files.

## Implementation and verification log

- Targeted extension inspection completed; feature-start source/staging hashes
  captured in `/tmp/omnirush/return_scope_baseline.json`.
- Implemented the four return tables, typed customer/admin inputs, order-locked
  return service, authenticated private evidence, owned customer endpoints,
  permission-gated admin endpoints and return tracking integration.
- Added nullable `Refund.return_request_id` and `manual_transfer_reference`.
  Existing financial provider/approval/recovery code remains the money path.
  Execution rechecks the passed inspection, explicit refund-request stage,
  captured item amount, active permissions/authority and available captured money.
- Generic order refunds reserve active return money. A fully refunded delivered
  purchase with a return record cannot be whole-order-restocked by a late scan
  on its original outbound AWB. Existing cancellation/RTO regressions pass.
- Customer delivered-order details now include item/quantity selection, every
  supported reason, details, private multi-photo submission/previews, return
  history, cancellation before shipping, manual courier tracking, pagination,
  refresh and pending-status polling.
- Admin `/returns` and `/returns/:id` include status/reason/customer/order
  search/filtering, responsive listing, purchase snapshots, private evidence,
  customer-visible review/inspection notes, legal next actions, tracking,
  receipt, inspection and existing refund-ledger links. Delivered admin orders
  link to their returns; existing refund rows link back to their return.
- UI mutation controls use current permission grants and return state. Empty
  permission arrays grant no actions. Loaders discard old filter/order responses;
  submission retries retain their original key and coalesce parallel clicks.

### Applied local PostgreSQL migration

- Migration: `alembic/versions/v7d8e9f0a1b2_product_returns.py`.
- Sole head: `u6c7d8e9f0a1` → **`v7d8e9f0a1b2`**.
- Applied to the explicitly authorized local development `sqlmodel` database
  using `ENVIRONMENT=development .venv/bin/python -m alembic upgrade head`.
- `alembic current --check-heads` passed at the new head.
- Feature-scoped Alembic metadata comparison: **zero differences**.
- All **37 mapped tables** and their mapped columns select against real DDL.
- Pre-/post-upgrade fingerprints preserve all original columns/rows across
  **33 existing tables**. New return tables are empty; existing refund rows have
  NULL return/manual-transfer fields.
- SQLite upgrade/constraints/downgrade regressions preserve existing refunds.
  A schema-only dump of the upgraded PostgreSQL database was tested in a named
  disposable database, including both new return races and five existing races.
  No development rows were copied into tests. All disposable databases removed.

### Final automated checks

| Check | Result |
| --- | --- |
| New return backend and migration contracts | **73 passed**, including two PostgreSQL races |
| Complete backend suite | **432 passed, zero skips**, 10 existing warnings |
| Actual migrated PostgreSQL DDL clone | **10 passed** |
| PostgreSQL concurrency coverage in full suite | **7 races passed** (five existing + two new) |
| Customer Node tests | **21 passed** (seven new return-flow checks) |
| Admin Node tests | **10 passed** (seven new return-flow checks) |
| Both production builds | Passed |
| Both full-project and configured release-scoped Oxlint commands | Passed; existing warnings only after return-file fixes |
| Locked dependency/release script with `--require-postgres` | Passed; 128 installed Python packages compatible |
| Alembic single-head/current-head and feature metadata | Passed |
| Backend `git diff --check`; added-file whitespace checks | Passed |
| Cross-repository feature-start content/staging comparison | Exactly **38 intended feature files**; other source/configuration/history and Git staging preserved |

The existing frontends are JavaScript projects and have no configured standalone
application typecheck; Vite's import/build validation and the configured lint/test
commands were run. The pre-existing storefront chunk-size and npm install-script
notice remain informational; no unrelated tooling/dependency changes were made.
Three newly generated content-test PNGs were identified by exact known test bytes
and removed; all 22 pre-existing uploads were preserved. Return evidence tests
use temporary private directories, not development/customer evidence.

Release gate invoked with a protected disposable PostgreSQL URL:

```bash
.venv/bin/python -m scripts.release_check \
  --storefront /home/yatnam/REACT/frontend \
  --admin /home/yatnam/REACT/ec-admin \
  --require-postgres
```

### Contract acceptance

| Requirement | Verification |
| --- | --- |
| Delivered/paid ownership and item eligibility | Real HTTP tests reject other customers, undelivered/cancelled/RTO/unpaid orders, uncollected COD, excluded variants and expired/missing-window dates |
| Partial/multiple/later legitimate quantities | Multi-item and repeated-partial tests; active/completed reservations; rejected/cancelled quantity release; integer-cent boundaries |
| Every reason and Other explanation | Seven reason cases plus strict invalid/blank/short Other/unknown-field validation |
| Duplicate/overlapping submissions | Stable-payload replay, changed-key-payload conflict, PostgreSQL overlap/replay race |
| Approval/rejection and legal stages | Required rejection note, preserved decision/inspection history, invalid-transition and failed-inspection tests |
| Receipt before refund | Tracking delivery receives only; manual receipt then explicit passed inspection; negative delivery/RTO labels cannot receive/refund |
| Existing refunds and financial authorization | Role limits/four-eyes/self-dealing/revoked permissions, pending/rejected approval, pending/completed/failed provider truth, retry, reconciliation and duplicate-refund PostgreSQL race |
| Unknown/committed-provider recovery | Unknown response and accepted-provider/failed-local-commit retries move money once through existing stable provider markers |
| COD repayment | Actual reference required; duplicate reference blocked; role-limited approval stages in existing ledger; zero PSP calls |
| Private evidence | Multiple bounded decoded/re-encoded images; executable/invalid types, count/size/pixel caps, protected owner/admin downloads, public-path misconfiguration, rollback/file cleanup |
| Audit consistency and unchanged cancellation | Same-transaction events/audit; failed commits leave no event/file/mutation; read paths are pure; cancellation fees/refunds/stock regression passes |
| Customer/admin async flows | Node tests cover selection/validation/files/stable submission, legal action/permission gates/notes/COD/tracking, and stale-result rejection |

## Configuration and operational use

Return policy settings are environment-backed and separate from cancellation
settings. Restart the API after changing them. JSON arrays are used for the list
settings. These defaults are explicit implementation defaults, not a new store
business-policy recommendation.

| Setting | Default / meaning |
| --- | --- |
| `RETURNS_ENABLED` | `true` |
| `RETURN_WINDOW_DAYS` | Unset: no imposed window. Set a positive integer for a decided store window. |
| `RETURN_EXCLUDED_VARIANT_IDS` | `[]`; JSON array of purchased variant UUID strings |
| `RETURN_REQUIRED_PHOTO_REASONS` | `[]`; JSON array of the reason values listed below |
| `RETURN_FEE_PERCENT` | `0`; separate captured return fee, never a cancellation fee |
| `RETURN_MAX_IMAGES` | `6` |
| `RETURN_IMAGE_MAX_BYTES` | `5242880` (5 MiB each), plus a 20-million-pixel decoder cap |
| `RETURN_STORAGE_DIR` | `private_storage/returns`; relative to backend root or an absolute private path; public uploads paths are refused |

Reason values: `damaged`, `wrong_product`, `defective`, `missing_accessory`,
`wrong_variant`, `changed_mind`, `other`. The net-merchandise allocation and
shipping/COD-fee exclusion are isolated in `merchandise_cents` in the return
service. Private storage must persist alongside the return/evidence database
records and be included with feature data backups. New directories/files use
0700/0600 permissions and the default private directory is Git-ignored.

### API entry points

All paths below are relative to `/api/v1`. Customer paths require an active
authenticated owner; admin paths require admin-audience authentication plus the
listed existing DB permission(s).

| Method/path | Purpose / permission |
| --- | --- |
| `GET /orders/{order_id}/return-eligibility` | Owned order eligibility, remaining quantities/value, effective policy/reasons |
| `POST /orders/{order_id}/returns` | Multipart `data` JSON (`idempotency_key`, `items`, `reason`, `description`) plus optional repeated `files` |
| `GET /returns?order_id=...&page=...&limit=...` | Owned paginated requests/details/history |
| `GET /returns/{id}` | Owned return detail |
| `POST /returns/{id}/cancel` | Owner cancellation before shipping |
| `POST /returns/{id}/tracking` | Owner attaches manual courier/tracking to approved return |
| `POST /returns/{id}/evidence` | Owner adds bounded photos before review decision |
| `GET /returns/{id}/evidence/{evidence_id}` | Private owned photo, no-store/nosniff |
| `GET /admin/returns` and `GET /admin/returns/{id}` | `orders.view`; paginated status/reason/search/order filters and detail |
| `GET /admin/returns/{id}/evidence/{evidence_id}` | `orders.view`; private authorized photo |
| `POST /admin/returns/{id}/decision` | `orders.update`; approve/reject with public note |
| `POST /admin/returns/{id}/cancel` | `orders.update`; cancel before shipping |
| `POST /admin/returns/{id}/tracking` | `orders.update` + `shipping.manage`; attach existing manual/Shiprocket reverse tracking |
| `POST /admin/returns/{id}/shipping/shiprocket` | `orders.update` + `shipping.manage`; create/reconcile reverse order and assign/resume its own AWB |
| `GET /admin/returns/shipping/simulator/shipments` | `orders.view` + `shipping.manage`; separately identified reverse shipments |
| `POST /admin/returns/{id}/shipping/simulator/trigger-event` | `orders.update` + `shipping.manage`; simulator-only return journey through the shared webhook handler |
| `POST /admin/returns/{id}/tracking/sync` | `orders.update` + `shipping.manage`; existing provider `get_tracking` |
| `POST /admin/returns/{id}/receive` | `orders.update`; confirm physical receipt |
| `POST /admin/returns/{id}/inspection` | `orders.update`; explicit boolean outcome and required note |
| `POST /admin/returns/{id}/refund` | `orders.refund`; existing refund authority/ledger/provider path; COD requires `manual_transfer_reference` |

Above-limit/self-order requests continue through existing
`POST /admin/refunds/{refund_id}/approve` / `reject` controls. Return status then
tracks the linked money outcome in the same transaction. Reverse shipments now
use the official Shiprocket return-order/AWB APIs described below. Other carriers
retain manual tracking attachment. Automatic inventory disposition remains a
separate operation from the delivered-return lifecycle.

## Reverse shipping follow-up (2026-10-05)

### Provider contract and controls

- Approved returns expose **Create Shiprocket Return** as the primary shipping
  action, with manual tracking under a secondary fallback. Accepted reverse IDs
  with no AWB expose **Assign return AWB**; uncertain creation exposes **Reconcile
  Shiprocket Return**. Detail shows independent IDs, reference, courier, AWB,
  provider sync and return tracking history.
- The existing service/auth/httpx integration uses documented external APIs:
  `POST /orders/create/return`, then `POST /courier/assign/awb` with `is_return: 1`.
  Return creation returns separate `order_id`/`shipment_id`, not an initial AWB.
  `GET /orders?search=<reference>` and `GET /orders/show/{id}` verify the exact
  `channel_order_id`, `is_return`, and unique shipment before recovering it.
- Customer pickup comes from historical purchase shipping/customer details;
  seller destination comes from `GET /settings/company/pickup`, matching one
  active `SHIPROCKET_PICKUP_LOCATION`. Selected purchased names/SKUs/quantities
  and unit prices are used; forward provider identifiers are never input to
  return creation. Return parcels are prepaid even for a collected COD sale.
- Existing parcel defaults (10 × 10 × 10 cm, 0.5 kg) are reused. No mandatory
  catalog fields or return/refund/cancellation policy settings are introduced.
- The existing simulator screen has a distinct **Customer return shipments**
  section with pickup/transit/out-for-delivery/delivered events, separate from
  outbound RTO. Payloads target the return's AWB through `process_tracking_event`.
  Delivery advances only to `received`; inspection, inventory and money retain
  their explicit existing boundaries. Reverse event simulation rejects a live
  provider selection.

Official Shiprocket Dev request references:
[Create a Return Order](https://www.postman.com/shiprocketdev/shiprocket-dev-s-public-workspace/request/4hsuoja/create-a-return-order)
and [Generate AWB for Return Shipment](https://www.postman.com/shiprocketdev/shiprocket-dev-s-public-workspace/request/rbouga2/generate-awb-for-return-shipment).
Request fields, lookup/pickup APIs and examples were inspected in the
[published Shiprocket Postman documentation](https://documenter.getpostman.com/view/12508904/TVCZbXSb)
and its public collection JSON. The primary API-docs host returned HTTP 502 during
inspection. Live courier calls were mocked in verification.

### Durable recovery and API limitations

- Migration `w8e9f0a1b2c3_return_shipments.py` follows `v7d8e9f0a1b2` and adds four
  nullable fields only to `return_requests`: unique reverse order/shipment IDs,
  a unique 20-digit provider reference, and a creation-request timestamp.
  Existing order shipping columns and return states are retained.
- Order-first locks serialize creation/assignment. A creation marker and its
  audit/event commit before the external POST. Accepted IDs and their audit/event
  commit before AWB assignment. The final AWB/state/event commit uses the existing
  return mutation boundary. Retries recover provider truth after lost responses
  or local commit failure and resume saved IDs rather than re-create shipments.
- The published contract has no native idempotency token. If a marked creation
  cannot be found, retries fail closed instead of issuing another POST. This also
  covers an interruption between marker persistence and network submission;
  unresolved references require account-side/operator reconciliation. A definite
  pre-submission/validation rejection clears the marker for a safe retry.
- AWB assignment depends on account return access, courier serviceability and
  balance. An AWB failure preserves the reverse order/shipment IDs for retry.
  Pickup scheduling/courier movement is not fabricated by creation or sync.
- The published return example leaves `pickup_location_id` empty for the new
  customer pickup address; this implementation follows that example rather than
  passing the seller warehouse ID as a customer pickup ID. Documentation also
  marks that field required, so accounts enforcing a pre-registered customer
  pickup ID may reject creation and need account-side address setup/manual
  tracking fallback. Such validation failures are surfaced without a blind retry.
- Other-courier fallback is available before booking. An existing/uncertain
  managed booking cannot acquire a second manual tracking number.

### Follow-up verification

- **457 backend tests passed, zero skips**, including the new three-request
  PostgreSQL booking race (one creation/one assignment) and all previous return,
  shipping, financial, cancellation and inventory regressions.
- **11 actual migrated PostgreSQL DDL clone checks passed**; protected schema-only
  disposable databases were removed after both clone and release checks.
- **24 reverse-shipping backend checks** plus an additive reverse migration
  upgrade/downgrade preservation check. Cases include distinct partial returns,
  approval/RBAC/audience gates, lost creation/AWB responses, failed checkpoints,
  exact provider endpoints/payloads, partial AWB retry, simulator/sync receipt,
  live-mode simulation refusal, and original forward IDs/AWB/tracking/stock/money
  preservation.
- Admin **13 Node tests passed** (three new reverse action/simulator flows);
  customer **21 passed**. Both release-scoped lint commands and production builds
  passed with existing informational warnings. The admin release lint scope now
  includes the edited simulator screen.
- Local development head is **`w8e9f0a1b2c3`**. Return-scoped metadata comparison
  has zero differences; all **37 mapped tables** select against actual DDL.
  Original-column fingerprints preserve all **37 existing tables**, and new
  fields on existing return rows remain NULL.
- Full locked release gate with `--require-postgres` passed; existing dependencies
  and Git staging were preserved. Feature-task source comparison is recorded in
  `/tmp/omnirush/reverse_scope_before.json`: exactly **16 intended files** changed;
  other source/configuration and prior work were preserved. Three newly generated
  exact-known-test PNGs were removed; all 22 pre-existing uploads were preserved.

### Simulator visibility correction

- Replaced the return section below the entire outbound grid with prominent
  **Outbound orders / Customer returns** tabs and shipment counts. Return cards
  show reason, purchased items/return quantities, current return/tracking state,
  independent AWB/courier, provider IDs when linked, and the return-detail link.
- The shipping list includes both API-created reverse shipments and separately
  attached Shiprocket return AWBs. Other-carrier and unbooked requests remain
  accessible through **View all return requests**; they do not receive fabricated
  simulator tracking. Attached Shiprocket AWBs use the same return event handler.
- Outbound and reverse requests load independently; API failures are rendered
  explicitly rather than appearing as zero returns or hiding the other list.
  Permission hydration refreshes the reverse list, and stale responses/unmounted
  loads cannot overwrite newer results.
- Focused return/shipping backend regressions: **112 passed, 3 PostgreSQL-only
  skips** with the isolated SQLite test URL. Admin **17 Node tests passed**;
  release-scoped lint and production build passed. The running admin dev server
  serves the new tab layout, and the existing local reverse listing was verified
  read-only to contain AWB, reason and purchased item details.

## Shiprocket simulator lifecycle correction (2026-10-06)

### Why outbound RTO is on an outbound order

Shiprocket has two different return meanings:

1. **RTO / Return to Origin** is a failed delivery of the original forward
   shipment. The same outbound AWB travels back to the seller. It belongs on the
   **Outbound orders** card and may restore the original undelivered order items
   when the courier reports the parcel delivered back to the origin.
2. **Customer return / reverse shipment** starts after a delivered purchase. It
   has a separate return order, shipment ID and AWB. It belongs in **Customer
   returns** and delivery changes only the existing return request to `received`.

Shiprocket’s support documentation describes RTO as the undelivered parcel being
returned to the origin, with RTO Initiated, RTO-OFD, RTO Delivered and RTO
Acknowledged stages. Its return-order documentation separately describes Return
Pending, Return Initiated, Return Pickup Generated, Return Picked Up, Return
In-Transit and Return Delivered. Sources inspected:

- [Shiprocket RTO statuses](https://support.shiprocket.in/support/solutions/articles/43000476628-what-is-rto-initiated-delivered-and-acknowledged-)
- [Shiprocket terminology, including forward/RTO/return-order statuses](https://support.shiprocket.in/support/solutions/articles/43000662858-important-terms-all-shiprocket-users-should-know)
- [Shiprocket return process](https://support.shiprocket.in/support/solutions/articles/152000000719-how-does-the-return-process-work-)
- [Shiprocket return-order creation](https://support.shiprocket.in/support/solutions/articles/43000463528-how-to-add-a-return-order-)
- [Published Shiprocket Postman API collection](https://documenter.getpostman.com/view/12508904/TVCZbXSb)

### Simulator controls and expected application changes

The simulator now presents the original forward branch as:

`Delivery failed (NDR)` → `RTO Initiated` → `RTO In Transit` → `RTO Out for Delivery` → `RTO Delivered — restocks` → `Acknowledge RTO`.

The “RTO Dispatched” wording is retained as a backend compatibility alias but is
not shown as the primary UI control because Shiprocket’s published order table
uses **RTO OFD** for the seller-origin delivery leg. The RTO buttons:

- use the original order’s forward AWB;
- send `is_return: 0` in the simulated webhook;
- move the original order to `rto` when RTO starts and keep it there through
  delivery/acknowledgement;
- record exact courier-phase labels in `shipment_status` (`RTO INITIATED`,
  `RTO IN TRANSIT`, `RTO OFD`, `RTO DELIVERED`, `RTO ACKNOWLEDGED`);
- restore original undelivered item stock exactly once at `RTO DELIVERED`;
- leave payment collection/refunds unchanged; and
- never replace the forward order’s AWB or provider IDs.

The separate customer-return controls use the reverse AWB and send the documented
return labels (`RETURN PICKED UP`, `RETURN IN TRANSIT`, `RETURN OUT FOR DELIVERY`,
`RETURN DELIVERED`) with `is_return: 1`. `RETURN DELIVERED` advances only to
`received`; the actual application response shows that inspection, refund and
forward AWB are unchanged.

Every simulator event now displays an **Actual application transition** summary:
before/after order or return state, courier status, stock-restoration effect,
money effect, receipt/inspection effect and forward-AWB preservation. The exact
webhook remains expandable below it. Outbound RTO and customer-return cards never
share an AWB or lifecycle handler lookup path.

### Numeric status-code correction

The previous simulator table incorrectly used a different status namespace for
tracking payloads. It now follows the published Shiprocket **Shipment/Tracking**
table: `9` RTO Initiated, `10` RTO Delivered, `14` RTO Acknowledged, `17` Out for
Delivery, `18` In Transit, `21` Undelivered, `40` RTO NDR, `41` RTO OFD and `42`
Picked Up. Shiprocket **Order** status codes are a separate namespace and are not
used to construct tracking webhook payloads. Human `current_status` labels remain
authoritative; an unknown numeric code is recorded as unknown rather than guessed.

The new lifecycle regressions cover NDR → RTO → delivered → acknowledged,
one-time restock, no payment mutation, forward-AWB preservation, exact
`is_return` separation, numeric status mapping and reverse-return receipt
isolation. Focused verification after this correction: **116 backend tests passed,
3 PostgreSQL-only skips**, and **17 admin Node tests passed**; release-scoped lint
passed with the existing warnings.
