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

## Phase 0 — Setup ✅

- Create/confirm the AWS account and an IAM user or SSO profile with least-privilege access
  (avoid using the root account and avoid broad `AdministratorAccess` long-term).
- Get a Google Cloud project + API key with the **Pollen API** enabled.
- **Decision: AWS SAM** for infra-as-code — simplest fit for a Lambda-centric app. The stack
  lives in [`infra/template.yaml`](../infra/template.yaml).
- `services/`, `ui/`, `docs/`, `scripts/`, `infra/` layout exists in the repo.

## Phase 1 — Explore the Pollen API & design the data model ✅

- `scripts/fetch_pollen_sample.py` prints a raw `forecast:lookup` response so you can confirm
  the shape for your own locations before trusting the parser.
- **Schema is designed and documented in [`DATA_MODEL.md`](DATA_MODEL.md)** — single-table
  design covering pollen readings, subscribers, and location config, with the five access
  patterns each resolving to one `Query` or `GetItem`.
- Anomaly rule for v1: alert when any watched pollen type's **Universal Pollen Index (UPI,
  0–5)** meets or exceeds a per-subscriber `threshold` (default 3). Types with no UPI data are
  skipped rather than treated as 0.

## Phase 2 — Ingestion Lambda ✅

- `services/src/ingest/` now calls the real Pollen API and parses the real response shape:
  - `pollen_api.py` — HTTP client plus pure parsing/threshold functions (unit tested)
  - `store.py` — DynamoDB access; all key construction in one place
  - `config.py` — env vars and SSM secret resolution
  - `handler.py` — orchestration: fetch → store → threshold check
- Writes **one item per location per forecast day**, keyed on the forecast date, which makes
  re-runs idempotent.
- Deployed as a Lambda on an **EventBridge schedule** (default `rate(6 hours)` — pollen
  forecasts don't change fast enough to warrant more).
- Verified end to end: deployed to `ca-central-1`, invoked manually, and the 3 resulting
  DynamoDB items were queried directly and confirmed correct — including `GRASS` stored as
  `upi: null` for a real no-coverage case, not treated as `0`.

## Phase 3 — Email notifier ✅

**Decoupled design chosen** (the more event-driven of the two options) — `ingest` now only
fetches and stores; a separate `notify` Lambda reacts to the table's DynamoDB Stream:

- `services/src/common/` — code shared by all three Lambdas: `pollen_api.py`, `store.py`,
  `config.py`, plus a new `ses.py` for sending.
- `services/src/ingest/handler.py` — trimmed down to fetch + store only.
- `services/src/notify/handler.py` — triggered by the table's **DynamoDB Stream**, filtered
  (via the event source's `FilterCriteria`) to only fire on new/updated `READING` items, so
  subscriber-claim writes on the same stream don't re-trigger it. Checks every confirmed
  subscriber for that location against the new reading, claims via
  `store.claim_notification()` (unchanged, still the per-day dedup guard), and sends through
  SES on a breach.
- `services/src/confirm/handler.py` — the double opt-in click target. New subscribers are
  created `PENDING` with a random `confirm_token`
  (`store.create_pending_subscriber()`); `get_subscribers()` only returns `CONFIRMED` ones, so
  no alerts go out until this Lambda's conditional update flips the status. Exposed via a
  **Lambda Function URL** (100% free, no API Gateway) rather than folding it into the Phase 4
  read API — it's a single public GET route with nothing else in common with that API.
- Email templates are plain text: location, date, breached type(s), UPI value for alerts;
  a confirm link for the opt-in email. `scripts/seed_subscriber.py` creates a test `PENDING`
  subscriber and prints (doesn't email) the confirm link, standing in for the real
  `POST /subscribe` flow until Phase 4/5 exist.
- SES: verify a sender identity (`aws ses verify-email-identity`). Starts in the SES sandbox —
  recipients must also be verified until production access is requested; see
  `docs/CONFIGURATION.md`. The notify function's IAM policy is scoped to that one sender
  identity ARN, not all of SES.
- Verified end to end on the deployed stack: seeded a `PENDING` subscriber, confirmed it
  through the live `ConfirmFunctionUrl` (including confirming a replayed confirm link
  correctly 400s as already-used), triggered `ingest`, and watched `notify` pick up the
  resulting stream records and send real alert emails — independently confirmed via
  `aws ses get-send-statistics` (delivery attempts count went up by exactly the number of
  alerts sent, 0 bounces/complaints/rejects), not just trusting the Lambda's own return value.

## Phase 4 — Read API ✅

**API Gateway HTTP API** (not REST — see Cost posture above), fronting a single `api` Lambda
that routes internally. Four routes rather than the three originally planned:

| Route | Backed by | Notes |
|-------|-----------|-------|
| `GET /locations` | Access pattern 1 | Not in the original list, but the Phase 5 location picker has to get its options from somewhere other than a hardcoded array |
| `GET /pollen/{location}/latest` | Access pattern 2 | |
| `GET /pollen/{location}/history?days=N` | Access pattern 3 | `days` defaults to 14, capped at 30 |
| `POST /subscribe` | `create_pending_subscriber` + SES | Creates the `PENDING` subscriber **and emails the confirm link**, completing the double opt-in loop `scripts/seed_subscriber.py` was standing in for |

- `services/src/api/handler.py` — one Lambda for all four routes. They share a `Store`, a cold
  start, and a deployment package; splitting them would multiply cold starts and buy no
  isolation at this scale. Routing is a dict lookup on the HTTP API payload v2.0 `routeKey`
  (`"GET /pollen/{location}/latest"`), not path parsing.
- `store.get_latest_reading()` is a **bounded backwards Query**, not a `GetItem` on today.
  Readings are keyed on the *forecast* date and the partition holds days ahead of today, so an
  unbounded "last item" would return the furthest-out forecast. Bounding on
  `sk <= READING#<today>` and reading in reverse returns today's reading — or the freshest
  older one if an ingest run failed, which is better than a 404.
- History ends at today rather than running out to the last forecast day: a trend chart that
  silently mixes past dates with days-ahead predictions on one axis reads as history when half
  of it isn't.
- **Throttling** is configured per route, not left to the account default: 10 req/s (burst 20)
  by default, and 2 req/s (burst 5) on `POST /subscribe`, since each accepted call there sends
  an email. This is the cost guard — a scraper or a runaway `useEffect` in Phase 5 is the
  realistic way request volume runs away on a public endpoint.
- **CORS** is handled by the HTTP API's `CorsConfiguration`, so API Gateway answers the
  preflight `OPTIONS` itself and no OPTIONS route ever reaches the Lambda. `CorsAllowOrigin`
  defaults to `*` (public read-only API, no cookies or credentials) — narrow it to the
  CloudFront origin once Phase 5/6 gives it a fixed domain.
- **Two security fixes the public endpoint forced**, neither of which mattered while
  subscribers were only created by a local script:
  - `create_pending_subscriber()` now writes with a condition (`attribute_not_exists(pk) OR
    status IN (PENDING, UNSUBSCRIBED)`) and returns `None` instead of overwriting. Without it,
    POSTing someone else's address would reset their `CONFIRMED` item to `PENDING` and silently
    stop their alerts. Re-posting while still `PENDING` is still allowed, which is what makes
    "resend the confirmation email" work.
  - `POST /subscribe` returns the **same 202 body** whether the address is new, pending, or
    already confirmed, so the endpoint can't be used to test which addresses are subscribed.
- IAM is three verbs (`GetItem`, `Query`, `PutItem`) written out explicitly rather than
  `DynamoDBCrudPolicy`, which would also hand a public endpoint `DeleteItem`, `UpdateItem`,
  and `Scan`.
- Unit tests (`services/tests/test_api.py`) cover the pure parts — body/query parsing,
  subscribe validation, date-range math, and the `Decimal`/`set` JSON encoding DynamoDB forces.

- Deployed to the live `allergy-tracker` stack in `ca-central-1` via a reviewed CloudFormation
  changeset (additive: new `HttpApi` + `ApiFunction`, in-place updates to the other three
  Lambdas, no data or deletions touched). Verified against the deployed stack: `GET /locations`,
  `GET /pollen/vancouver/latest`, and `GET /pollen/vancouver/history` all returned real data;
  `POST /subscribe` against an already-`CONFIRMED` address returned its 202 no-op response and
  left the DynamoDB item unchanged (same `confirm_token`/`created_at`), confirming the
  overwrite-guard fix holds in production, not just in unit tests.
- Teardown/cost-safety: `docs/TEARDOWN.md` documents how to fully delete the stack (`sam delete`)
  plus the two resources it creates outside CloudFormation (the SSM parameter, the SES identity).
  A Budget alert (`$1`/month, fires at $0.01 actual spend, emails on breach) was already in place
  before this deploy.

## Phase 5 — Web dashboard (React) — built, not yet hosted

- Vite + React + TypeScript, scaffolded in `ui/` (see `ui/README.md`). `src/api.ts` is the only
  thing that talks to the backend, calling the Phase 4 Read API -- the browser never touches
  DynamoDB.
- Today's view (`TodaySummary`): current UPI + category per pollen type for the selected
  location.
- Trend chart (`TrendChart`): last 14 days via `GET /pollen/{location}/history`, built with
  Recharts. Uses the dataviz skill's validated 3-color categorical palette (one fixed color per
  pollen type, not cycled), a single 0-5 axis (no dual-axis), legend + tooltip so identity never
  depends on color alone, and light/dark tokens driven by `prefers-color-scheme`.
- Subscribe form (`SubscribeForm`): email + threshold, posts to `/subscribe`, surfaces the API's
  202/error message.
- Verified with a headless-browser smoke test (Playwright) against the **live deployed API**,
  light and dark mode, zero console errors -- not just a local mock.
- Visual/brand pass: hand-drawn per-allergen icons (`src/icons.tsx`) sized for legibility, a
  small brand identity (logo mark, gold accent color, card elevation) so the dashboard reads as
  more than the default Vite starter. Re-verified with the same headless-browser check after.
- **Hosted:** live at **https://d3myi08baazbck.cloudfront.net**, ahead of the rest of Phase 6 —
  see the hosting note under Phase 6 below. `CorsAllowOrigin` on the backend stack was narrowed
  from `*` to that exact CloudFront domain once it existed, per the plan below; verified the
  live site still loads with no console errors after the change.

## Phase 6 — Deployment & CI — CI/CD wired, awaiting one-time AWS setup

Goal: push a commit to `main` and have both the backend and dashboard deploy themselves, with
tests gating the merge — no long-lived AWS credentials stored anywhere.

**`.github/workflows/ci.yml` is written and its non-AWS jobs verified locally** (`ruff check`,
`pytest`, `sam validate --lint` on all three templates, `npm run lint`/`npm run build` all pass —
see the commands each job runs). What's not yet done, and needs the repo owner to do it by hand
once (CI shouldn't grant itself deploy access) — steps are in
[`CONFIGURATION.md`](CONFIGURATION.md#cicd-one-time-setup-phase-6):

1. Deploy `infra/github-oidc-template.yaml` and add its `RoleArn` output as the
   `AWS_DEPLOY_ROLE_ARN` GitHub repo secret.
2. Add the lifecycle rule to the SAM-managed artifacts bucket (the "nice-to-have" below, now
   with the actual command).

Until those are done, `deploy-backend`/`deploy-frontend` will fail on `AWS_DEPLOY_ROLE_ARN` not
being set — the test/lint/build jobs run and gate merges regardless, so this is safe to merge
before that setup happens.

### Dashboard hosting (done, ahead of the rest of this phase)

- `infra/hosting-template.yaml` — a **second, independent CloudFormation stack**
  (`allergy-tracker-ui`), deliberately separate from the backend stack so either can be torn down
  without touching the other (see `docs/TEARDOWN.md`). Plain CloudFormation, not a Serverless
  Transform — S3 and CloudFront aren't serverless-compute resources, so the SAM transform buys
  nothing here.
- Private S3 bucket (all public access blocked) + CloudFront distribution reaching it through
  **Origin Access Control** (the modern replacement for the legacy OAI), so the bucket is never
  directly reachable.
- `PriceClass_100` (cheapest edge tier) and the default `*.cloudfront.net` certificate — no ACM,
  no Route 53 hosted zone, since a custom domain isn't needed yet.
- Deploy was manual (`npm run build` in `ui/`, then `aws s3 sync ui/dist/ s3://<bucket>`) —
  now wired into the `deploy-frontend` job below, once the one-time AWS setup is done.

### Backend (SAM)

- `sam build && sam deploy` remains the manual/local fallback (`infra/samconfig-backend.toml`
  now makes the deploy half non-interactive: `sam deploy --config-file
  infra/samconfig-backend.toml`); CI's `deploy-backend` job runs the same two commands.
- **One environment (`prod`) to start.** A personal, low-traffic project doesn't need a
  permanently-running parallel `dev` stack duplicating DynamoDB/Lambda/CloudWatch costs. If you
  want a scratch stack while actively developing, `sam deploy --stack-name allergy-tracker-dev`
  spins up a second, independently-named stack — `sam delete --stack-name allergy-tracker-dev`
  tears it down when you're done so it isn't left running (and billing, however slightly) in the
  background.
- SAM's auto-created deployment-artifacts S3 bucket accumulates old build zips on every deploy.
  A lifecycle rule fixes this, but it's account-level S3 config, not something in
  `infra/template.yaml` to deploy — see the one-time command in
  [`CONFIGURATION.md`](CONFIGURATION.md#cicd-one-time-setup-phase-6).

### GitHub Actions — `.github/workflows/ci.yml`

- **`test-python`, `validate-sam`, `build-ui`** run on every PR and every push to any branch.
  No AWS credentials needed, so these are safe to run even on PRs from forks:
  - `test-python`: `ruff check` + `pytest` (added `services/pyproject.toml` for ruff config and
    `services/requirements-dev.txt` for `ruff`/`pip-audit`; running ruff surfaced and fixed a
    handful of pre-existing style issues so CI starts green — see the diff).
  - `validate-sam`: `sam validate --lint` against all three templates (`template.yaml`,
    `hosting-template.yaml`, and the new `github-oidc-template.yaml` below).
  - `build-ui`: `npm run lint && npm run build` against a placeholder `VITE_API_BASE_URL` — a
    build-only check, no real API calls happen here.
- **`deploy-backend`, `deploy-frontend`** run only on push to `main`, and only after the jobs
  above pass. Authenticated via **GitHub OIDC federation**
  (`aws-actions/configure-aws-credentials` with `role-to-assume`) — *not* long-lived
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` secrets. GitHub issues a short-lived token per run
  that the IAM role trusts only for `repo:<org>/<repo>:ref:refs/heads/main`; nothing durable ever
  sits in GitHub Secrets except the role's ARN itself, which grants nothing on its own.
  - `deploy-backend`: `sam build && sam deploy --config-file infra/samconfig-backend.toml`.
  - `deploy-frontend`: rebuilds the dashboard against the just-deployed stack's real
    `ApiEndpoint` (fetched via `aws cloudformation describe-stacks`, not hardcoded), syncs
    `dist/` to the hosting bucket, then invalidates `/index.html` only — Vite's content-hashed
    JS/CSS filenames mean nothing else needs invalidating.
  - Both jobs are safe to re-run on failure: `sam deploy` is idempotent via CloudFormation
    changesets, and `aws s3 sync` is idempotent by nature.
- **The deploy role itself is `infra/github-oidc-template.yaml`**, a separate, plain
  CloudFormation template (no SAM transform — it's pure IAM, nothing serverless) deployed by
  hand, once, outside CI — see the one-time setup steps in
  [`CONFIGURATION.md`](CONFIGURATION.md#cicd-one-time-setup-phase-6). Its policy is scoped to
  the `allergy-tracker`/`allergy-tracker-ui` stacks and `allergy-tracker-*`-named resources
  specifically (Lambda functions, the one DynamoDB table, log groups, the schedule, the alarm,
  the two S3 buckets), not `AdministratorAccess` or blanket `cloudformation:*`/`s3:*` on the
  account — same least-privilege principle as the Phase 0 IAM user and the Phase 4 API Lambda's
  three-verb DynamoDB policy.
- Verified locally, short of an actual AWS deploy (which needs the OIDC role to exist first —
  see above): `ruff check`, `pytest`, `sam validate --lint` on all three templates, `npm run
  lint`, and `npm run build` all pass as of this change.

### Nice-to-have once the basics work

- `cfn-lint` (or `sam validate --lint`, already in `validate-sam`) and `test-python` as
  **required status checks** on `main` via branch protection.
- `pip-audit` / `npm audit` as a non-blocking scheduled (weekly) job rather than a per-PR gate —
  `pip-audit` is already in `services/requirements-dev.txt`, just not wired into a workflow yet.

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

Lambda → EventBridge → DynamoDB → DynamoDB Streams → SES → Lambda Function URLs → API Gateway →
CloudWatch alarms. Each phase above adds exactly one or two new pieces, so you're never debugging
more than one unfamiliar service at a time.