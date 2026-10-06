# Release checks and deployment

## Reproducible local verification

Use Python **3.12**, uv **0.12.0**, Node **24.18.1** (`nvm use` in each frontend), npm **11**.
Backend `uv.lock` and both `package-lock.json` files are required release inputs.
Do not substitute an unlocked install. Test dependencies live in the locked `test` group.

From the backend repository, with the existing frontend repositories available:

```bash
.venv/bin/python -m scripts.release_check \
  --storefront /home/yatnam/REACT/frontend \
  --admin /home/yatnam/REACT/ec-admin
```

This checks lock consistency, installs locked backend/test dependencies, checks
installed dependency compatibility, runs the complete backend suite, prints the
Alembic head, checks whitespace, installs both frontends with `npm ci`, runs their
Node regressions/scoped remediation lint, and builds both production bundles.
Failures stop the command. Existing whole-project lint debt is not silently treated
as clean; `lint:release` scopes the changed remediation paths and still reports warnings.

Tests override runtime DB/provider credentials and never use the live DATABASE_URL.
For required concurrency verification, create an explicitly disposable PostgreSQL
database named `remediation_test*`, set `REMEDIATION_TEST_DATABASE_URL`, and add
`--require-postgres`. The fixture creates/removes only a random test schema. Without
that URL, five concurrency tests skip; SQLite is not evidence of PostgreSQL locks.

## Production startup and readiness

Set `ENVIRONMENT=production`. Startup rejects non-PostgreSQL DBs, short JWT secrets,
wildcard CORS, dummy payments/simulator shipping, missing active-provider webhook
credentials, missing mail/chat credentials, and localhost/plain-HTTP frontend URLs.
It checks DB connectivity and **exactly one matching Alembic head** before policy
initialization or scheduler startup. It never automatically migrates the live DB.

Required configuration:
- `DATABASE_URL`; unique `JWT_SECRET_KEY` (at least 32 characters); explicit `CORS_ORIGINS`.
- HTTPS `FRONTEND_URL` and `ADMIN_FRONTEND_URL` for reset/invite links.
- `PAYMENT_PROVIDER=stripe` plus `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`,
  `STRIPE_WEBHOOK_SECRET`, or `razorpay` plus `RAZORPAY_KEY_ID`,
  `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`. Retain old provider credentials
  while historical attempts/refunds need recovery. Set matching regional currency/locale.
- `SHIPPING_PROVIDER=shiprocket`, `SHIPROCKET_EMAIL`, `SHIPROCKET_PASSWORD`,
  pickup location/pincode and a matching `SHIPROCKET_WEBHOOK_TOKEN` at the provider.
- Gmail `EMAIL_PROVIDER=gmail`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, or SendGrid
  `EMAIL_PROVIDER=sendgrid`, `SENDGRID_API_KEY` and the existing verified sender config.
- `GROQ_API_KEY`; optional chat limits default to 10 messages/principal/minute,
  5 sessions/principal/minute, 100 messages globally/minute, 24-hour sessions.
- Run the existing scheduler: outbox job every 30 seconds and expiry job at the
  configured `PENDING_ORDER_EXPIRY_JOB_MINUTES`. Multiple workers rely on PostgreSQL locks.

`/health/live` means process alive. `/health/ready` returns 503 for configuration,
connectivity, migration or production scheduler failure and exposes no error secrets.
Readiness does not claim provider credentials are accepted or mail is delivered.

## Ordered migration and reconciliation

Back up the database and user `uploads/` and rehearse restoration. Keep application,
lockfiles, migration artifacts and both frontend bundles from the same verified release.
On an isolated PostgreSQL clone, run the complete existing migration chain through:

`n9b0c1d2e3f4 → o0c1d2e3f4a5 → p1d2e3f4a5b6 → q2e3f4a5b6c7 →
r3f4a5b6c7d8 → s4a5b6c7d8e9 → t5b6c7d8e9f0 → u6c7d8e9f0a1`.

Inventory backfill conservatively marks historic terminal releases without changing
stock. Reconcile historic missed releases/no-restock choices manually. COD correction
requires reviewing cash collections lacking successful COD payment rows; it removes
delivery-only paid flags and is deliberately not reversed on downgrade. Old partial
refund fulfillment state and old unowned in-memory chat histories cannot be reconstructed.

After the clone rehearsal, execute the migration command in the deployment
environment before starting updated workers (`uv run --locked alembic upgrade head`).
Verify readiness, both same-origin `/api/v1` frontend reverse proxies and WebSockets.
Do not stamp a revision to bypass a failed upgrade. Prefer roll-forward; restoring a
DB backup after new money movements requires provider reconciliation, not blind rollback.

## Operational smoke checks

Verify provider sandboxes for ambiguous intent/refund recovery and signed webhooks;
mail acceptance/retry; checkout/cancellation/RTO stock; repeated partial refunds;
COD delivery then explicit collection; catalog later pages/UUID category links;
chat guest/login/logout isolation; authenticated shipping documents and report failures.

Monitor outbox due age/attempts/last_error, stuck payment creation `submitting` rows,
failed/pending refunds and provider mismatches, uncollected COD, scheduler failures,
readiness failures, and chat 429/503 rates. Restrict DB access/retention for client secrets,
mail reset/invite links and chat history. Never log capability/authorization headers or
legacy chat session_id queries. Expired chat state is removed on new session issuance.

Configure TLS, request-body/connection limits at the existing reverse proxy and trusted
ASGI proxy peers; do not trust arbitrary forwarded-IP headers. Preserve `uploads/` and
the existing Chroma data/model cache. Provider, browser, PostgreSQL migration and backup
restore checks require real isolated environments; local SQLite/build success alone
does not assert deployment readiness.
