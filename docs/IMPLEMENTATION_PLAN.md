# Implementation plan

Phases are ordered so each one produces something runnable/testable before moving on, and so
AWS services are introduced one at a time rather than all at once.

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

- Add API Gateway (HTTP API) + a small Lambda (or a couple of routes) for:
  - `GET /pollen/{location}/latest`
  - `GET /pollen/{location}/history?days=14`
  - `POST /subscribe` (email, location, threshold)
- This is what the dashboard will call — it should not read DynamoDB directly from the browser.

## Phase 5 — Web dashboard (React)

- Scaffold with Vite (see `ui/README.md`, already sketched).
- Today's view: current pollen levels per type for a selected location.
- Trend chart: last N days, using Chart.js/Recharts against the history endpoint.
- Subscribe form: email + location + threshold, posts to `/subscribe`.

## Phase 6 — Deployment & CI

- `sam build && sam deploy` (or CDK equivalent) for the backend.
- Static hosting for the dashboard: S3 + CloudFront, or Vercel/Netlify if you'd rather not
  manage that AWS piece yet.
- Optional: GitHub Actions workflow to deploy on push to `main`.

## Phase 7 — Observability & polish

- CloudWatch alarms on Lambda errors and throttles.
- Structured logging in the ingestion Lambda (location, pollen values, whether an alert fired).
- Nice-to-haves once the core loop works: multiple locations per subscriber, unsubscribe link,
  Cognito-based auth if you want accounts instead of bare email capture.

## Suggested order of AWS services introduced

Lambda → EventBridge → DynamoDB → SES → API Gateway → CloudWatch alarms. Each phase above adds
exactly one or two new pieces, so you're never debugging more than one unfamiliar service at a
time.
