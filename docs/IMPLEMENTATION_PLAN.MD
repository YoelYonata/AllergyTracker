# Implementation plan

Phases are ordered so each one produces something runnable/testable before moving on, and so
AWS services are introduced one at a time rather than all at once.

## Cost posture

This is a low/no-traffic personal project, so every phase below is chosen to stay near **$0/month**,
not just "cheap":

| Service | Why it stays free here |
|---------|-------------------------|
| Lambda | Free tier (1M requests + 400,000 GB-seconds/month) is **permanent**, not a 12-month trial. This project runs a handful of invocations a day. |
| DynamoDB | `PAY_PER_REQUEST` billing — no idle capacity charge. At this item count/traffic, bill rounds to cents. |
| EventBridge Scheduler | No charge for the rule itself; you only pay for the Lambda invocations it triggers. |
| API Gateway (HTTP API) | **Not permanently free**, but close to it here: 1M requests/month free for the first 12 months, then $1.00/million after — REST APIs are $3.50/million, which is why Phase 4 specifically uses the **HTTP API** type, not REST. At hobby traffic (tens to low-thousands of requests/month) this rounds to fractions of a cent even off the free tier. |
| SES | ~$0.10 per 1,000 emails. This project sends at most a few alert emails a day — negligible. |
| S3 + CloudFront | CloudFront's free tier (1 TB transfer + 10M requests/month) was made **permanent** in 2021, not a 12-month trial. S3 storage for a small React build is pennies. |
| SSM Parameter Store (SecureString) | Free. This is *why* Phase 0/3 use Parameter Store instead of Secrets Manager, which charges ~$0.40/secret/month for a feature (rotation) this project doesn't need. |
| CloudWatch Alarms/Dashboards | First 10 alarms and first 3 dashboards are free forever. Phase 7 stays under both. |

**Things to deliberately avoid**, since they're the usual ways a "free" serverless project stops
being free:
- **No VPC for the Lambdas.** Nothing here needs private networking, and putting a Lambda in a
  VPC to reach the internet requires a NAT Gateway (~$32/month) — by far the single easiest way
  to blow the budget on a toy project.
- **No Route 53 hosted zone** unless you specifically want a custom domain (~$0.50/month per
  zone). The CloudFront default domain (`*.cloudfront.net`) works fine for a hobby dashboard.
- **CloudWatch Logs retention must be set explicitly.** The default is "Never expire," which
  silently accumulates storage charges. Phase 7 sets a retention period on every log group.
- Alternative worth knowing about: a **Lambda Function URL** is 100% free (no per-request
  charge, ever) and would work for a single-route read API. This plan uses API Gateway anyway
  because part of the point of this project is hands-on API Gateway experience — but if cost
  ever becomes a real concern, swapping Phase 4's HTTP API for a Function URL is the escape
  hatch.

## Phase 0 — Setup

- Create/confirm the AWS account and an IAM user or SSO profile with least-privilege access
  (avoid using the root account and avoid broad `AdministratorAccess` long-term).
- Get a Google Cloud project + API key with the **Pollen API** enabled.
- **Decision: AWS SAM** for infra-as-code — simplest fit for a Lambda-centric app. The stack
  lives in [`infra/template.yaml`](../infra/template.yaml).
- `services/`, `ui/`, `docs/`, `scripts/`, `infra/` layout exists in the repo.

## Phase 1 — Explore the Pollen API & design the data model

- `scripts/fetch_pollen_sample.py` prints a raw `forecast:lookup` response so you can confirm
  the shape for your own locations before trusting the parser.
- **Schema is designed and documented in [`DATA_MODEL.md`](DATA_MODEL.md)** — single-table
  design covering pollen readings, subscribers, and location config, with the five access
  patterns each resolving to one `Query` or `GetItem`.
- Anomaly rule for v1: alert when any watched pollen type's **Universal Pollen Index (UPI,
  0–5)** meets or exceeds a per-subscriber `threshold` (default 3). Types with no UPI data are
  skipped rather than treated as 0.

## Phase 2 — Ingestion Lambda

- `services/src/ingest/` now calls the real Pollen API and parses the real response shape:
  - `pollen_api.py` — HTTP client plus pure parsing/threshold functions (unit tested)
  - `store.py` — DynamoDB access; all key construction in one place
  - `config.py` — env vars and SSM secret resolution
  - `handler.py` — orchestration: fetch → store → threshold check
- Writes **one item per location per forecast day**, keyed on the forecast date, which makes
  re-runs idempotent.
- Deployed as a Lambda on an **EventBridge schedule** (default `rate(6 hours)` — pollen
  forecasts don't change fast enough to warrant more).
- Remaining: run it against a real API key and confirm the stored items look right.

## Phase 3 — Email notifier

The ingestion handler already does the threshold check and returns a list of alerts it *would*
send, and `store.claim_notification()` already handles per-day deduplication. What's left is
actually sending them.

- Verify a sender identity in **SES** (starts in the SES sandbox — recipients must also be
  verified until you request production access).
- Two options for wiring it up:
  - Simplest: the ingestion Lambda calls SES directly on the alerts it collected.
  - More decoupled (better for learning event-driven design): the table already has a
    **DynamoDB Stream** enabled — have a separate Lambda consume it, check thresholds, and
    send via SES. Recommended if you want the extra AWS surface area.
- Keep the email template simple at first: location, date, pollen type(s), UPI value.
- Add the double opt-in flow: new subscribers start at `status: PENDING` and only move to
  `CONFIRMED` after clicking a link — `get_subscribers()` already filters to `CONFIRMED` only.

## Phase 4 — Read API

- Add API Gateway — **HTTP API type, not REST API** (see Cost posture above: ~3.5x cheaper per
  request and simpler to define) — + a small Lambda (or a couple of routes) for:
  - `GET /pollen/{location}/latest`
  - `GET /pollen/{location}/history?days=14`
  - `POST /subscribe` (email, location, threshold)
- This is what the dashboard will call — it should not read DynamoDB directly from the browser.
- Add basic throttling (HTTP APIs default to a sane account-level rate limit already) so a
  scraper or bug in the frontend can't run up request volume unbounded.

## Phase 5 — Web dashboard (React)

- Scaffold with Vite (see `ui/README.md`, already sketched).
- Today's view: current pollen levels per type for a selected location.
- Trend chart: last N days, using Chart.js/Recharts against the history endpoint.
- Subscribe form: email + location + threshold, posts to `/subscribe`.

## Phase 6 — Deployment & CI

Goal: push a commit to `main` and have both the backend and dashboard deploy themselves, with
tests gating the merge — no long-lived AWS credentials stored anywhere.

### Backend (SAM)

- `sam build && sam deploy` stays the manual/local fallback; CI runs the same two commands.
- **One environment (`prod`) to start.** A personal, low-traffic project doesn't need a
  permanently-running parallel `dev` stack duplicating DynamoDB/Lambda/CloudWatch costs. If you
  want a scratch stack while actively developing, `sam deploy --stack-name allergy-tracker-dev`
  spins up a second, independently-named stack — `sam delete --stack-name allergy-tracker-dev`
  tears it down when you're done so it isn't left running (and billing, however slightly) in the
  background.
- SAM's auto-created deployment-artifacts S3 bucket accumulates old build zips on every deploy.
  Add a lifecycle rule (e.g. expire noncurrent versions after 30 days) so it doesn't grow
  unbounded — small cost, but a good habit to build now.

### GitHub Actions

- **On every PR / push to a branch:** `pytest`, `sam validate --lint`, and a Python linter
  (`ruff`). No AWS credentials needed for this job, so it's safe to run even on PRs from forks.
- **On push to `main`:** `sam build && sam deploy --no-fail-on-empty-changeset`, authenticated via
  **GitHub OIDC federation** (`aws-actions/configure-aws-credentials` with `role-to-assume`) —
  *not* long-lived `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` secrets. GitHub issues a short-lived
  token per run that the IAM role trusts only for this repo + the `main` branch; nothing durable
  ever sits in GitHub Secrets. This is worth doing even on a hobby project — it's the current best
  practice and there's no extra cost to it.
- Scope the deploy role to exactly what SAM needs (CloudFormation, plus the specific
  Lambda/DynamoDB/IAM/SSM/EventBridge actions the stack uses) — same least-privilege principle as
  the Phase 0 IAM user, not `AdministratorAccess`.
- **Frontend job:** `npm ci && npm run build` in `ui/`, sync `dist/` to the S3 bucket, then
  invalidate CloudFront. If the build's JS/CSS filenames are content-hashed (Vite does this by
  default), only `index.html` needs invalidating — keeps invalidations minimal (though the first
  1,000 paths/month are free anyway). Scope the S3 sync's `--delete` to the dashboard's own
  prefix/bucket only.
- Both jobs should be safe to re-run on failure: `sam deploy` is naturally idempotent via
  CloudFormation changesets, and an S3 sync is idempotent by nature.

### Nice-to-have once the basics work

- `cfn-lint` (or `sam validate --lint`) and the test job as **required status checks** on `main`
  via branch protection.
- `pip-audit` / `npm audit` as a non-blocking scheduled (weekly) job rather than a per-PR gate.

## Phase 7 — Observability & polish

Goal: know a run failed (or is about to) from an alert, not from noticing the dashboard looks
stale — while keeping log/metric storage inside the always-free tiers.

### Structured logging

- Adopt **`aws-lambda-powertools`** (Logger/Metrics/Tracer) instead of hand-rolled
  `logging`/`print` calls — JSON-structured logs, automatic request/correlation IDs, and
  CloudWatch Embedded Metric Format (EMF) for custom metrics without extra API calls or cost.
  It's just a pip dependency; no new AWS resource.
- Minimum fields per run: location, forecast fetch success/failure, readings written, alerts
  evaluated, alerts sent vs. skipped-as-duplicate. Enough to answer "did today's run work?" from
  CloudWatch Logs Insights without re-invoking anything.

### Metrics & alarms

- Custom EMF metrics (free — well under the always-free custom-metrics allowance at this scale):
  `AlertsSent`, `BreachesDetected`, `LocationsFailed` per run.
- Alarms (first 10/month are always free; this project needs about five):
  - Lambda `Errors` ≥ 1 (already in the template)
  - Lambda `Throttles` ≥ 1
  - Lambda `Duration` p99 approaching the configured timeout — catches a slow upstream API before
    it becomes an outright timeout
  - SES bounce/complaint rate — not just a cost concern; a high complaint rate risks SES pausing
    your sending ability entirely
  - EventBridge `FailedInvocations` on the schedule rule, as a backstop in case the trigger itself
    (not the Lambda) fails
- Route every alarm to **one SNS topic with an email subscription**, so "in ALARM" actually reaches
  you instead of sitting unread in a console. SNS email delivery is free at this volume.

### Cost-safe logging

- Set an explicit **CloudWatch Logs retention period** (e.g. 14–30 days) on every Lambda's log
  group in the SAM template. The default is "Never expire," which quietly accumulates storage
  cost forever — a one-line fix per function.

### Tracing (defer until it's useful)

- Enable X-Ray (`Tracing: Active` in the SAM `Globals` block) once the Phase 4 Read API exists —
  that's the point where a request actually spans more than one Lambda/service and tracing starts
  paying for itself. 100k traces/month are free, well above this project's volume. Skip it while
  there's only the single ingestion Lambda; tracing one function in isolation adds little.

### Dashboard

- One CloudWatch dashboard (first 3/account are free forever): invocations/errors/duration per
  Lambda, DynamoDB consumed capacity, and the custom `AlertsSent`/`BreachesDetected` metrics.

### Nice-to-haves once the core loop works

- Multiple locations per subscriber, unsubscribe link, Cognito-based auth if you want accounts
  instead of bare email capture.

## Suggested order of AWS services introduced

Lambda → EventBridge → DynamoDB → SES → API Gateway → CloudWatch alarms. Each phase above adds
exactly one or two new pieces, so you're never debugging more than one unfamiliar service at a
time.