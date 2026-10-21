# COD Reconciliation

Sales → **COD Reconciliation** tracks two distinct money events:

1. **Customer cash collection** — the courier collects cash on delivery. When
   Shiprocket reports `DELIVERED` for a COD order, the tracking webhook records
   exactly one `Payment(provider=cod)` row automatically. The
   `POST /admin/cod/orders/{id}/collect` endpoint remains available for legacy
   or exception cases (for example a delivery recorded before this change, or a
   courier that does not send webhooks).
2. **Courier remittance** — Shiprocket (or another courier) pays the merchant
   for those collected orders, usually net of COD/weight charges. This is
   tracked by the new remittance batches and **never creates a Payment row**.

### Automatic cash collection on delivery

`process_tracking_event` treats a Shiprocket `DELIVERED` scan as strong evidence
that the courier collected the COD cash. For an order with
`payment_method=cod` and `payment_status=cod_pending` it calls the same
`record_cod_collection` logic used by the manual endpoint:

- Creates one `Payment(provider=cod, status=succeeded)` for `grand_total` and
  flips `orders.payment_status` to `paid`.
- Writes a `cod.collected` audit row with `actor_id=None`, `source=webhook` and
  `collected_by_email=shiprocket-webhook`, so auto-collections are
  distinguishable from admin actions.
- Commits payment, order mutation and audit row in the same webhook transaction.
- Is idempotent: a duplicate `DELIVERED` webhook (or an admin clicking **Mark
  collected** afterwards) finds the existing succeeded COD payment and makes no
  second `Payment`. Duplicate webhook deliveries are ignored, not retried.

Only `cod_pending` COD orders are affected. Online-paid orders and scans before
`DELIVERED` never create a COD payment. A courier can occasionally mark a parcel
delivered incorrectly; because the audit row records `source=webhook`, these can
be identified and corrected through the normal payment/refund review path.

A remittance confirmation only allocates the payout against
`orders.cod_remitted_amount` and updates `orders.cod_remittance_status`
(`pending` → `partial` → `complete`). Revenue and the payment ledger are
unchanged, so remittance can never double-count a COD sale.

## Shiprocket reality

Shiprocket publishes tracking webhooks and wallet/statement APIs, but **no COD
remittance API or webhook**. Batches therefore arrive in one of three ways:

| Source | How | Notes |
| --- | --- | --- |
| `csv` | Download the COD Remittance report from the Shiprocket panel (Billing → COD Remittance) and import it | Primary production path; column mapping is configurable |
| `manual` | Enter the CRF / payout lines in the admin UI | For finance teams without a usable CSV |
| `simulator` | `POST /admin/cod/remittances/simulate` or **Simulate (synthetic)** | Development aid only; clearly labelled and production-gated |

### Synthetic data rules

- Simulator batches are stored with `source=simulator` and
  `raw_meta.synthetic=true`, and the UI shows a persistent **SYNTHETIC — not
  Shiprocket data** badge.
- The simulator is allowed outside production. In production it is blocked
  unless `COD_REMITTANCE_SIMULATOR_ENABLED=true`.
- The downloadable fixture (`GET /admin/cod/remittances/sample-fixture`) is a
  synthetic sample with fake AWBs/CRFs and an explicit data note. It is not
  real Shiprocket data.
- Never present simulator/fixture output as a real remittance.

## Data model

### `cod_remittances`

Batch header: `crf_id`, normalized `crf_key`, provider, remittance date, status
(`pending`, `discrepancy`, `reconciled`, `void`), gross COD, deductions, expected
net, bank credit/UTR/date/account, accepted difference, source, notes, raw
mapping metadata, importer/reconciler, timestamps. `crf_key` is
`lower(trim(crf_id))`; a partial unique index enforces it only for non-void
batches.

### `cod_remittance_items`

One row per CSV/manual line: AWB, order reference, COD, deductions, net,
allocated amount, match status/note, source row snapshot, line hash.

### `orders`

Additive columns:

- `cod_remitted_amount` — cumulative net remittance allocated to the order.
- `cod_remittance_status` — `pending` | `partial` | `complete`.
- `cod_remitted_at` — set when the order becomes complete.

No existing order/payment/refund behavior is changed by the migration.

## Matching and discrepancies

Lines are matched by AWB first, then by order number / Shiprocket order id.
Statuses:

| Status | Meaning | Confirm behaviour |
| --- | --- | --- |
| `matched` | COD order, delivered, cash collected, amount agrees, no in-flight batch | Allocates net |
| `amount_mismatch` | Line COD differs from order total, or net ≤ 0 | Accept or exclude a COD mismatch; zero-net lines must be excluded |
| `order_not_found` | No AWB/order match | Exclude |
| `not_cod` | Online-paid order | Exclude |
| `not_delivered` | Order has not reached delivered status | Wait/collect, then accept; or exclude |
| `cash_not_collected` | No successful COD `Payment` yet | Normally cleared automatically by the `DELIVERED` webhook; for legacy rows collect manually, then accept or re-import |
| `already_remitted` | Fully remitted, or already in another in-flight (pending/discrepancy) batch | Exclude or void the other batch |
| `duplicate` | Identical line/order repeated in the same file | Exclude |
| `adjustment` | Explicitly excluded by an admin | Allocates nothing |

A batch with any open flagged line is created as `discrepancy` and cannot be
confirmed. Resolving every line (accept/exclude) recalculates the batch totals
from the non-excluded lines and moves it back to `pending`.

Duplicate protection:

- An **active** `crf_id` cannot be imported twice (409), case-insensitively.
  Voiding the batch frees the reference, so a corrected re-import can use the
  same CRF; the voided row remains in the audit trail.
- A second in-flight batch cannot claim the same order; it is flagged
  `already_remitted`. Imports lock matched orders in deterministic id order and
  re-run matching after the lock, so concurrent imports cannot both claim one.
- Within a file, identical lines and repeated orders are flagged as duplicates.
- Database-level partial uniqueness converts a concurrent duplicate CRF race
  into a 409 instead of a 500.

## Partial remittances

`instant`/early COD style payouts can pay an order in instalments. After a
confirmed batch, the order stays `partial` until cumulative allocated net
reaches `grand_total`. A later batch may claim the remaining amount.
Reconciled batches do **not** block a later instalment; only pending or
discrepancy batches do.

## Bank receipt confirmation

`POST /admin/cod/remittances/{id}/confirm` requires UTR, bank credit amount/date
and at least one matched line. While any flagged line remains, it returns 409.

- Every matched line must have a positive allocation equal to its line net, and
  the matched-line total must equal the batch expected net. A short/rounded
  allocation is rejected before anything is written.
- All matched orders are locked in deterministic id order and revalidated for
  COD payment method, delivered status, successful cash collection, non-complete
  remittance state and remaining COD. If any check fails, confirmation returns
  409 and no order/batch changes are committed.
- If the bank credit equals the expected net (±0.01), confirmation succeeds.
- If not, the first attempt returns 409 with `expected`, `bank_credit` and
  `difference`. The admin must resubmit with `accept_difference=true` and a
  `difference_reason`. The difference and reason are stored on the batch and in
  the audit log. The original expected net/deductions are retained; `bank_credit`
  and `difference` record what actually landed.
- Confirmation is idempotent in effect: a reconciled batch cannot be confirmed
  again (409), and a concurrent second confirmation also gets 409. Each order’s
  allocation is the full matched line amount, never silently capped.
- Voided batches cannot be confirmed; reconciled batches cannot be voided.

> **Allocation semantics:** `cod_remitted_amount` is the net remittance
> allocated to the order, exactly as matched on the line. If a line’s net is
> larger than the remaining COD, it stays flagged and cannot be accepted;
> exclude it or correct the batch. Deductions therefore leave an order `partial`
> unless a later instalment/adjustment line covers the difference. This is
> intentional so deductions are visible rather than silently written off. There
> is no one-click “write off courier deduction” action yet.

## CSV format

Download the blank header from
`GET /admin/cod/remittances/sample-template`:

```csv
awb,order_number,cod_amount,deductions,net_amount,crf_id,remittance_date,utr
```

Only an AWB or order number is required per line. Amounts accept `₹`, commas
and blank cells; blank net is derived as `COD − deductions`. The importer also
recognises common Shiprocket labels (`AWB Code`, `Collectable Amount`,
`Charges`, `Remittance Amount`, etc.) and suggests a mapping in the preview.

Validation rejects amount/reference problems with HTTP 400:

- negative COD, deductions, net or remitted amounts;
- a provided net that does not equal `COD − deductions`;
- a provided `remitted_amount` that does not equal the net;
- a file containing more than one non-blank CRF reference (import each CRF
  separately);
- a row CRF that differs from the batch CRF.

Oversized uploads are rejected with HTTP 413: more than 5,000 data rows or files
over 5 MB.

Import is a two-step flow:

1. `POST /admin/cod/remittances/import/preview` (multipart) — parses, suggests
   mapping, matches, returns rows and totals. **Creates nothing.**
2. `POST /admin/cod/remittances/import` (multipart) — creates the batch after
   the admin confirms CRF id, date, mapping and notes.

## Permissions

- `cod.view` — view summary, pending collection (with `orders.update`), batches
  and details; download template/fixture/export.
- `cod.reconcile` — import, manual entry, resolve lines, confirm bank receipt,
  void, simulator.

Seeded grants: admin and manager get both; staff gets neither. Cash collection
continues to require `orders.update`.

## API summary

```
GET  /admin/cod/summary
POST /admin/cod/collect-bulk                         (orders.update)
GET  /admin/cod/remittances                           (cod.view)
GET  /admin/cod/remittances/sample-template           (cod.view)
GET  /admin/cod/remittances/sample-fixture            (cod.view)
POST /admin/cod/remittances/import/preview            (cod.reconcile)
POST /admin/cod/remittances/import                    (cod.reconcile)
POST /admin/cod/remittances                           (cod.reconcile, manual)
POST /admin/cod/remittances/simulate                  (cod.reconcile, synthetic)
GET  /admin/cod/remittances/{id}                      (cod.view)
GET  /admin/cod/remittances/{id}/export               (cod.view)
POST /admin/cod/remittances/{id}/resolve              (cod.reconcile)
POST /admin/cod/remittances/{id}/confirm              (cod.reconcile)
POST /admin/cod/remittances/{id}/void                 (cod.reconcile)
```

`GET /admin/cod/pending` is unchanged. `POST /admin/cod/orders/{id}/collect`
still works for legacy/exception collection, but a `DELIVERED` Shiprocket
webhook now performs the same collection automatically.

Audit actions: `cod.remittance.imported`, `cod.remittance.item_resolved`,
`cod.remittance.reconciled`, `cod.remittance.voided` (plus existing
`cod.collected`). `cod.collected` records `source=webhook` with no actor for
automatic collection, or the acting admin's id with `source=admin` for manual
collection. Resolution notes, accepted-difference reasons, bank reference
details and the client IP (when supplied by the request/proxy) are recorded in
the same transaction as the change.

## Migration

Head after this change: `a1b2c3d4e5f7` (parent `z1b2c3d4e5f6`, which remains
unchanged because it was already applied).

```bash
cd FAST/Com
uv run alembic upgrade head
# rollback only the active-CRF migration:
uv run alembic downgrade -1
```

`a1b2c3d4e5f7` adds `crf_key`, backfills it from `lower(trim(crf_id))`, replaces
the global unique CRF index with a normal index plus the partial unique
`uq_cod_remittances_crf_active`, and leaves all financial rows intact. It fails
clearly if pre-existing active rows already collide case-insensitively; resolve
those manually rather than deleting payouts. Downgrade restores the old unique
index and suffixes duplicate voided CRF references with their row id if needed.
Upgrade, downgrade and re-upgrade were exercised against the configured
development Postgres database. An isolated database also verified the `crf_key`
backfill, rejection of a concurrent case-insensitive active duplicate and the
downgrade suffixing of duplicate voided references; `alembic check` shows no COD
drift (only the pre-existing unrelated drift).

## Tests

```bash
cd FAST/Com
PYTHONPATH=. uv run pytest tests/test_cod_remittance.py tests/test_cod_accounting.py \
  tests/test_rbac.py -q
PYTHONPATH=. uv run pytest tests/test_release_gates.py -q

cd ../REACT/ec-admin
npm run test
npm run lint
npm run build
```

Test coverage includes CSV parsing/mapping, invalid/mixed-CRF amount rejection,
matching flags, duplicate CRF/AWB protection, void/re-import, manual batches,
partial instalments, discrepancy blocking/exclusion, revalidation of order
state and allocations at confirmation, explicit bank-difference acceptance, no
second Payment row, simulator production gating/labelling, summary queues, audit
notes/IP, RBAC grants and staff direct-API 403s. COD collection tests cover
auto-collection on a `DELIVERED` webhook, idempotency across duplicate delivery
webhooks, non-COD orders, pre-delivery scans, and the audit distinction between
`source=webhook` (no actor) and `source=admin` (acting admin). One integration
test drives the existing Shiprocket shipping simulator to deliver a COD order,
then creates and reconciles a synthetic remittance batch. PostgreSQL-only
concurrency tests for simultaneous import claims, duplicate-CRF races,
confirmations and cash collection skip unless `REMEDIATION_TEST_DATABASE_URL`
points at an isolated `remediation_test*` database.

## Limitations / follow-ups

- Shiprocket has no COD remittance API, so there is no automatic sync. A panel
  CSV or manual entry is always required.
- The importer understands the headers listed above; unknown layouts can still
  be mapped manually, but multi-sheet workbooks are not supported (export to
  CSV first).
- Courier deductions that reduce net below order total leave the order
  `partial`; there is no dedicated deduction write-off flow yet.
- Remittance reversal/correction after reconciliation is intentionally blocked;
  finance must use a later batch/adjustment.
- The simulator is a development aid, not a Shiprocket integration and not
  evidence of Shiprocket API support.
