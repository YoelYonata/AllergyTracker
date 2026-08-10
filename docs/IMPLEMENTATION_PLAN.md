# Implementation plan

Phases are ordered so each one produces something runnable/testable before moving on, and so
AWS services are introduced one at a time rather than all at once.

## Phase 0 — Setup

- Create/confirm the AWS account and an IAM user or SSO profile with least-privilege access
  (avoid using the root account and avoid broad `AdministratorAccess` long-term).
- Get a Google Cloud project + API key with the **Pollen API** enabled.
- Decide on infra-as-code: AWS SAM (simplest for a Lambda-centric app) or CDK (more general,
  more TypeScript/Python code). Recommendation: **SAM** for this project's scope.
- `services/`, `ui/`, `docs/`, `scripts/` layout already exists in the repo.

## Phase 1 — Explore the Pollen API & design the data model

- Do a sample fetch against the Pollen API (see question 4 / `scripts/fetch_pollen_sample.py`)
  and confirm the exact response shape for the locations you care about.
- Design the DynamoDB table(s). Suggested single-table design:

  | PK                     | SK                      | Attributes |
  |-------------------------|--------------------------|------------|
  | `LOC#<location_id>`     | `READING#<iso_timestamp>` | pollen index per type (tree/grass/weed), category, raw payload |
  | `LOC#<location_id>`     | `SUB#<email>`            | threshold, subscribed pollen types, created_at |

  This lets you query "all readings for a location" and "all subscribers for a location" with
  a single `Query` on the partition key, using the sort-key prefix to filter.
- Decide the anomaly rule for v1 (e.g. "any pollen type's index >= 4" or a per-user threshold
  stored on the subscriber record).

## Phase 2 — Ingestion Lambda

- Extend `services/src/ingest/handler.py` to call the real Pollen API (it already has the
  scaffolding for `POLLEN_API_URL`/`POLLEN_API_KEY`) and parse the real response shape from
  Phase 1 instead of the generic `pollen_level`/`pollen_type` guesses.
- Write one DynamoDB item per location per pollen type per day.
- Add the anomaly check: after writing, compare against subscriber thresholds for that location.
- Deploy as a Lambda function, triggered by an **EventBridge scheduled rule** (e.g. every
  6 hours — pollen forecasts don't change fast enough to need more).
- This is the first "real" AWS phase: Lambda, IAM execution role, EventBridge, DynamoDB.

## Phase 3 — Email notifier

- Verify a sender identity in **SES** (starts in the SES sandbox — recipients must also be
  verified until you request production access).
- Two options for wiring it up:
  - Simplest: the ingestion Lambda calls SES directly when it detects an anomaly.
  - More decoupled (better for learning event-driven design): enable a **DynamoDB Stream** on
    the readings table, and have a separate Lambda consume the stream, check thresholds, and
    send via SES. Recommended if you want the extra AWS surface area.
- Keep the email template simple at first: location, date, pollen type(s), index value.

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
