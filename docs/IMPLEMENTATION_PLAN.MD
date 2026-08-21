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

## History range & retention ✅

Added after Phase 5/6 landed, ahead of Phase 7: the trend chart originally showed a fixed 14 days
with no way to see further back, and readings sat in DynamoDB for a full year (`READING_TTL_DAYS`
defaulted to 365) even though nothing ever read that far. Two changes, both free:

- **Selectable range.** `GET /pollen/{location}/history?days=N` now accepts up to 90 (was 30);
  the dashboard's trend chart got a 30-day/90-day toggle (`TrendChart`, state lifted to `App.tsx`
  so switching ranges just re-fetches with a different `days` value — no new endpoint). 30 is the
  default: it's the common case and the smaller payload, and DynamoDB Query cost/latency scale
  with items returned, so a page load doesn't pull 90 days nobody asked to see yet.
- **Retention capped to match.** `READING_TTL_DAYS` default dropped from 365 to 90 — there's no
  reason to keep data the UI can never show. Deletion is DynamoDB's native **TTL**, not a cleanup
  Lambda: items past their `ttl` epoch-seconds attribute (set once, at write time, in
  `store.put_reading()`) are removed by DynamoDB in the background at no cost -- TTL deletes don't
  consume write capacity or invoke anything, unlike a scheduled delete job would. See
  [`DATA_MODEL.md`](DATA_MODEL.md#pollen-reading) for the item shape and
  [`CONFIGURATION.md`](CONFIGURATION.md#environment-variables) for the env var.
- **Why 90 and not, say, 60 or 180:** 90 covers a full pollen season (tree/grass/weed seasons
  each run a few months) while keeping per-location item count -- and therefore Query cost, which
  is what actually scales with data volume here -- an order of magnitude smaller than the old
  365-day retention. `PAY_PER_REQUEST` billing means this was never a *capacity* cost, only a
  storage-and-Query-size one, both already close to free; the cap is about keeping the trend
  chart meaningful (a season, not a blurry year) more than about the dollars.
- TTL deletion isn't instant -- DynamoDB documents it as "typically within 48 hours" of
  expiry -- so briefly having 91-92 days of data around is expected, not a bug.

## Phase 5 — Web dashboard (React) ✅

- Vite + React + TypeScript, scaffolded in `ui/` (see `ui/README.md`). `src/api.ts` is the only
  thing that talks to the backend, calling the Phase 4 Read API -- the browser never touches
  DynamoDB.
- Today's view (`TodaySummary`): current UPI + category per pollen type for the selected
  location.
- Trend chart (`TrendChart`): 30 or 90 days via `GET /pollen/{location}/history`, built with
  Recharts. Uses the dataviz skill's validated 3-color categorical palette (one fixed color per
  pollen type, not cycled), a single 0-5 axis (no dual-axis), legend + tooltip so identity never
  depends on color alone, and light/dark tokens driven by `prefers-color-scheme`. A range toggle
  in the chart header lets the user switch between the two windows -- see "History range &
  retention" below for why 30/90 and not something else.
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

## Phase 6 — Deployment & CI ✅

Goal: push a commit to `main` and have both the backend and dashboard deploy themselves, with
tests gating the merge — no long-lived AWS credentials stored anywhere.

**Live end to end.** `.github/workflows/ci.yml` runs `ruff check`/`pytest`/`sam validate
--lint`/`npm run lint`/`npm run build` on every PR and push, and `deploy-backend` +
`deploy-frontend` have both gone green on a push to `main` via the GitHub OIDC role in
`infra/github-oidc-template.yaml`. The one-time setup (deploy the OIDC role, add its `RoleArn` as
the `AWS_DEPLOY_ROLE_ARN` GitHub repo secret, add the artifacts-bucket lifecycle rule) is done —
see [`CONFIGURATION.md`](CONFIGURATION.md#cicd-one-time-setup-phase-6) if it ever needs redoing
in a different account.

Getting from "written" to "actually deploys" took three follow-up fixes, each surfaced by a real
failed run rather than caught by `sam validate --lint` (which doesn't check IAM trust policies or
account-specific bucket names):

1. **GitHub's OIDC `sub` claim now embeds immutable numeric org/repo IDs, not just names**
   (`repo:{org}@{orgId}/{repo}@{repoId}:ref:...`, a change GitHub made across 2025/2026 so a
   renamed/transferred repo can't inherit an old trust relationship). The trust policy's
   `StringLike` match on `{org}/{repo}:ref:...` alone no longer matched — switched to an exact
   `StringEquals` against the full claim, with `GitHubOrgId`/`RepositoryId` template parameters
   (found via `gh api users/<org>` / `repos/<org>/<repo>`).
2. **`samconfig-backend.toml`/`samconfig-hosting.toml` used `resolve_s3 = true`**, which asks the
   SAM CLI to look up (or create) the managed artifacts bucket at deploy time — fine locally
   where credentials can call `s3:CreateBucket`/`ListAllMyBuckets`, but the CI role is
   deliberately scoped to only the one named bucket (see `infra/github-oidc-template.yaml`), so
   the lookup failed under least-privilege. Pinned to an explicit `s3_bucket = "..."` instead —
   same bucket, no runtime discovery.
3. **`sam deploy` creates a CloudFormation *change set* under the hood**, which — because
   `template.yaml` uses the SAM transform — requires `cloudformation:CreateChangeSet` on the
   `AWS::Serverless-2016-10-31` transform ARN specifically, a permission separate from
   `cloudformation:*` on the stack itself. Added once the failure showed the gap.

None of these three needed touching the app code or the CI workflow file itself — all three
fixes live in `infra/github-oidc-template.yaml` / `infra/samconfig-*.toml`, which is the point of
keeping deploy IAM in its own least-privilege template: tightening it is iterative and low-risk
to get wrong in the direction of "too narrow, fails safe."

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
- Deploy was manual at first (`npm run build` in `ui/`, then `aws s3 sync ui/dist/ s3://<bucket>`)
  — now fully replaced by the `deploy-frontend` job below.

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
  that the IAM role trusts only for an exact match on
  `repo:<org>@<org-id>/<repo>@<repo-id>:ref:refs/heads/main` (see fix #1 above); nothing durable
  ever sits in GitHub Secrets except the role's ARN itself, which grants nothing on its own.
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
- Verified for real: `deploy-backend` and `deploy-frontend` have both gone green on a push to
  `main`, not just validated locally.

### Nice-to-have once the basics work

- `cfn-lint` (or `sam validate --lint`, already in `validate-sam`) and `test-python` as
  **required status checks** on `main` via branch protection.
- `pip-audit` / `npm audit` as a non-blocking scheduled (weekly) job rather than a per-PR gate —
  `pip-audit` is already in `services/requirements-dev.txt`, just not wired into a workflow yet.

## Phase 7 — Observability & polish ✅

Goal: know a run failed (or is about to) from an alert, not from noticing the dashboard looks
stale — while keeping log/metric storage inside the always-free tiers.

### Structured logging

- Adopted **`aws-lambda-powertools`** (`Logger`/`Metrics`/`Tracer`) in all four Lambdas, replacing
  the hand-rolled `logging.getLogger()` calls. Every log line is now JSON with a correlation ID
  (`function_request_id`), cold-start flag, and whatever keyword fields the call site passed
  (`logger.info("Stored readings for location", location_id=..., readings_written=...)`),
  queryable from **CloudWatch Logs Insights** without re-invoking anything. `aws-xray-sdk` had to
  be added alongside `aws-lambda-powertools` explicitly — Powertools' `Tracer` imports it lazily
  and doesn't declare it as a hard dependency.
- Each handler's `if __name__ == "__main__":` block used to call `handler(event, None)` for local
  runs. Powertools' `Logger.inject_lambda_context` reads `function_name`/`aws_request_id`/etc.
  straight off the context object, so `None` now raises `AttributeError` — fixed with a small
  `common/local_context.py` (`LocalLambdaContext`, one shared fake context) rather than
  duplicating a stub class in all four files.

### Metrics & alarms

- Custom EMF metrics, `AllergyTracker` namespace, dimensioned by `service` (free — CloudWatch's
  Embedded Metric Format is a specially-shaped log line, no extra API call or cost beyond the
  logging that already happens): `ingest` emits `LocationsFailed`/`ReadingsWritten`, `notify`
  emits `AlertsSent`/`BreachesDetected`.
- Six alarms (first 10/month are always free), all routed to one **SNS topic with an email
  subscription** (`AlarmTopic`, the required `AlarmEmail` template parameter — AWS emails a
  subscription-confirmation link after the first deploy that has to be clicked before alarms
  actually notify anyone):
  - `IngestFunctionErrorAlarm` — Lambda `Errors` ≥ 1 (already existed; now also wired to the SNS
    topic instead of firing silently into the console)
  - `IngestFunctionThrottleAlarm` — Lambda `Throttles` ≥ 1
  - `IngestFunctionDurationAlarm` — `Duration` p99 ≥ 48s (80% of the 60s Globals timeout) —
    catches a slow Pollen API before a run starts timing out outright
  - `IngestScheduleFailedInvocationsAlarm` — EventBridge Scheduler `TargetErrorCount` ≥ 1, as a
    backstop for the *trigger* failing rather than the Lambda. **Deviates from the plan as
    originally written here**: the metric is `TargetErrorCount`, not `FailedInvocations` —
    `FailedInvocations` belongs to classic EventBridge Rules (`AWS/Events`), not EventBridge
    Scheduler (`AWS/Scheduler`), which is what `ScheduleV2` actually deploys. Scheduler also only
    publishes metrics per schedule *group*, not per individual schedule, so the ingest schedule
    now lives in its own dedicated `IngestScheduleGroup` (`allergy-tracker`) rather than the
    account's shared "default" group, giving the alarm an unambiguous dimension to key off.
  - `SesBounceRateAlarm` / `SesComplaintRateAlarm` — SES's automatic account-level
    `Reputation.BounceRate`/`Reputation.ComplaintRate` metrics (`AWS/SES`, no configuration set
    needed), thresholded at 5%/0.1% — below the ~10%/0.5% levels at which SES itself would
    throttle or pause sending, so the alarm is the early warning, not the same signal twice.
  - Scoped to ingest specifically (not duplicated across `notify`/`confirm`/`api`) rather than
    aiming for one of every alarm type per function: ingest is the one Lambda talking to an
    external API on an unattended schedule, the likeliest place for a silent failure to go
    unnoticed. Six alarms stays close to the "about five" this phase was scoped for while every
    one earns its place; extending `Errors`/`Throttles` to the other three functions is a cheap
    future addition (still well under the free 10) if they turn out to need it.

### Cost-safe logging

- `LogRetentionDays` (default 30) already existed on every Lambda's log group before this phase —
  see "History range & retention" and the cost posture table above. No change needed here.

### Tracing

- `Tracing: Active` in the SAM `Globals.Function` block, now that the Phase 4 Read API exists and
  a request can actually span more than one Lambda. 100k traces/month are free. `Policies` isn't
  a Globals-supported property for `AWS::Serverless::Function` (`sam validate --lint` catches
  this immediately if attempted), so each function declares its own `AWSXRayDaemonWriteAccess`
  managed policy individually rather than once at the top.

### Dashboard

- One CloudWatch dashboard (`allergy-tracker`, first 3/account are free forever, stack output
  `DashboardUrl`): invocations/errors/duration per Lambda, DynamoDB consumed read/write capacity,
  and the four custom EMF metrics above.

### Verification

- `python -m pytest` (58 tests) and `ruff check` pass unchanged — the pure functions the test
  suite exercises were untouched; only logging/metrics/tracing wiring around them changed.
- `sam validate --lint` passes on all three templates.
- Each handler's `__main__` entry point smoke-tested locally end to end (`python -m
  confirm.handler`, `python -m notify.handler`, plus an import check on `ingest`/`api`),
  confirming structured JSON logs, EMF metric lines, and the cold-start metric all emit
  correctly with the new `LocalLambdaContext`.
- Not yet verified against the live deployed stack — `sam deploy` wasn't run as part of this
  change; see docs/CONFIGURATION.md#observability-phase-7 for the `AlarmEmail` parameter needed
  before deploying, and remember to confirm the SNS subscription email afterward.

### Nice-to-haves once the core loop works

- Multiple locations per subscriber, unsubscribe link, Cognito-based auth if you want accounts
  instead of bare email capture.

## Suggested order of AWS services introduced

Lambda → EventBridge → DynamoDB → DynamoDB Streams → SES → Lambda Function URLs → API Gateway →
CloudWatch alarms. Each phase above adds exactly one or two new pieces, so you're never debugging
more than one unfamiliar service at a time.