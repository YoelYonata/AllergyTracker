# Configuration & secrets

## Where the Google Pollen API key goes

**Never commit the key.** `.env` and `.env.*` are already gitignored — keep it that way.

`config.py` resolves the key in this order, so the exact same handler code runs locally and in
Lambda without any environment-specific branching in application logic:

1. `GOOGLE_POLLEN_API_KEY` — plaintext env var, **local development only**.
2. `POLLEN_API_KEY_PARAM` — the *name* of an SSM Parameter Store SecureString holding the key —
   **the AWS/Lambda path**.

### Local development

`services/.env` (gitignored) should hold:

```
GOOGLE_POLLEN_API_KEY=AIza...your-key...
DDB_TABLE_NAME=allergy-tracker
```

`config.py` loads it via `python-dotenv` if the package is installed; nothing else to do.

### On AWS — SSM Parameter Store (SecureString)

Store the key once, from your own machine:

```bash
aws ssm put-parameter \
  --name /allergy-tracker/google-pollen-api-key \
  --value "AIza...your-key..." \
  --type SecureString \
  --overwrite
```

Then the Lambda's environment only needs the *parameter name*, not the value:

```
POLLEN_API_KEY_PARAM=/allergy-tracker/google-pollen-api-key
```

The Lambda fetches it with `WithDecryption=True` on cold start and caches it in a module-level
variable so warm invocations skip the extra SSM call. `infra/template.yaml` grants the ingestion
function `ssm:GetParameter` on exactly that one parameter path, plus `kms:Decrypt` on the default
SSM key — not broad SSM access.

**Why not a plain Lambda environment variable?** Lambda env vars are encrypted at rest, but the
plaintext is visible to anyone who can call `lambda:GetFunctionConfiguration` or open the console
— and in practice you'd end up putting the value in the SAM template to deploy it, which puts the
key straight into git. Parameter Store keeps the secret and the deployable config separate; that
separation is the actual point, not the encryption.

**SSM Parameter Store vs. Secrets Manager:** Secrets Manager adds built-in rotation and
cross-account sharing for ~$0.40/secret/month. A Parameter Store `SecureString` is **free** at
the standard tier and does everything this project needs — see the cost posture note in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). Reach for Secrets Manager only if you need
automatic rotation later (typically for database credentials, which this project doesn't have).

### Restrict the key in Google Cloud too

Defense in depth, worth doing even though the key is stored safely on the AWS side:

1. Google Cloud Console → **APIs & Services → Credentials** → your key.
2. **API restrictions** → *Restrict key* → select **Pollen API** only, so a leaked key can't be
   used against other billable Google APIs.
3. Skip **Application restrictions** (IP allowlisting): Lambda's outbound IPs are dynamic unless
   the function sits in a VPC behind a NAT Gateway with an Elastic IP — and per the cost posture
   note, a NAT Gateway (~$32/month) is exactly the kind of cost this project avoids.
4. Set a **quota limit** on the Pollen API so a leaked key can't run up a bill on its own.

## Environment variables

| Variable | Where | Required | Purpose |
|----------|-------|----------|---------|
| `GOOGLE_POLLEN_API_KEY` | Local only | One of these two | The API key, in plaintext |
| `POLLEN_API_KEY_PARAM` | Lambda | One of these two | SSM parameter name holding the key |
| `DDB_TABLE_NAME` | Both | Yes (defaults to `allergy-tracker`) | DynamoDB table name |
| `FORECAST_DAYS` | Ingest only | No (default `3`) | Days to fetch per run, 1–5 |
| `READING_TTL_DAYS` | Ingest only | No (default `90`) | How long readings live before TTL expiry — matches the dashboard's 90-day max history range, see [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md#history-range--retention) |
| `DEFAULT_THRESHOLD` | Notify + api | No (default `3`) | Fallback UPI threshold if a subscriber has none set |
| `SES_SENDER_EMAIL` | Notify + api | Yes | Verified SES identity used as the "From" address on alert and confirmation emails |
| `CONFIRM_BASE_URL` | Api Lambda, and local `seed_subscriber.py` | Yes, to subscribe | The deployed `ConfirmFunction`'s Function URL. The template wires this into the api Lambda automatically; only set it by hand for local script runs — see the stack Outputs after `sam deploy` |

## Observability (Phase 7)

- **Structured logs.** All four Lambdas use `aws-lambda-powertools`'s `Logger` instead of the
  stdlib `logging` module — every log line is JSON with a correlation ID
  (`function_request_id`), cold-start flag, and whatever keyword fields the call site passed
  (e.g. `logger.info("Stored readings for location", location_id=..., readings_written=...)`).
  Query them in **CloudWatch Logs Insights** rather than grepping raw text, e.g.:
  ```
  fields @timestamp, location_id, readings_written, max_upi_today
  | filter @message = "Stored readings for location"
  | sort @timestamp desc
  ```
- **Custom metrics (EMF).** `ingest` emits `LocationsFailed`/`ReadingsWritten`; `notify` emits
  `AlertsSent`/`BreachesDetected` — all in the `AllergyTracker` CloudWatch namespace, dimensioned
  by `service`. Emitted via CloudWatch's Embedded Metric Format (a specially-shaped log line),
  so there's no extra API call or cost beyond the log line itself already being written.
- **X-Ray tracing.** `Tracing: Active` in the template's `Globals`, now that the Phase 4 Read API
  gives requests something to actually span. 100k traces/month are free — see the cost posture
  note in `IMPLEMENTATION_PLAN.md`.
- **Alarms**, all published to one SNS topic (`AlarmTopic` / `allergy-tracker-alarms`):
  ingest `Errors`, ingest `Throttles`, ingest `Duration` p99 (approaching the 60s timeout), the
  EventBridge Scheduler `TargetErrorCount` (the trigger itself failing, not the Lambda), and SES
  account-level `Reputation.BounceRate`/`Reputation.ComplaintRate`. **The `AlarmEmail` parameter
  is required** — after the first deploy, AWS emails that address an SNS subscription
  confirmation link; alarms won't actually notify anyone until it's clicked.
- **Dashboard.** One CloudWatch dashboard (`allergy-tracker`) with per-Lambda
  invocations/errors/duration, DynamoDB consumed capacity, and the custom pipeline metrics above.
  The stack's `DashboardUrl` output links straight to it.
- **Log retention.** Every Lambda's log group has an explicit `RetentionInDays` (the
  `LogRetentionDays` parameter, default 30) — CloudWatch Logs defaults to "Never expire," which
  quietly accumulates storage cost forever.

## Read API (Phase 4)

The dashboard talks to an **API Gateway HTTP API** rather than reading DynamoDB from the
browser. Its base URL is the stack's `ApiEndpoint` output:

```bash
aws cloudformation describe-stacks --stack-name allergy-tracker \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text
```

| Route | Purpose |
|-------|---------|
| `GET /locations` | Locations the dashboard's picker offers |
| `GET /pollen/{location}/latest` | Today's reading for one location |
| `GET /pollen/{location}/history?days=N` | Trend data; `days` defaults to 30, max 90 (the dashboard's toggle offers 30 or 90) |
| `POST /subscribe` | `{"email", "location", "threshold"?, "pollen_types"?}` — creates a `PENDING` subscriber and emails the confirm link |

**Two template parameters affect it:**

- `CorsAllowOrigin` (default `*`) — the browser origin allowed to call the API. `*` is fine
  while the dashboard has no fixed domain; the API is public and read-only and sends no cookies
  or credentials. Narrow it to the CloudFront origin once Phase 6 deploys one:
  `sam deploy --parameter-overrides CorsAllowOrigin=https://d111111abcdef8.cloudfront.net`
- Throttling is set in the template, not here: 10 req/s (burst 20) by default and 2 req/s
  (burst 5) on `POST /subscribe`. Raise these in `infra/template.yaml` if you ever have real
  traffic — but they're the main thing standing between a public endpoint and an unbounded
  request bill.

**`POST /subscribe` and the SES sandbox.** The confirmation email goes out through the same
sandboxed SES identity as the alerts, so while SES is in the sandbox the endpoint will accept a
subscription from any address but only *deliver* the confirm link to verified ones. That's the
right failure mode for a personal project — the subscriber just never confirms — but it's worth
knowing before wondering why a test signup went quiet.

## Email sending (SES)

Phase 3 adds two more Lambdas: `notify` (sends alert emails) and `confirm` (the double opt-in
click target). Before either can actually deliver mail:

1. **Verify a sender identity.** A personal email you control is fine for this project:
   ```bash
   aws ses verify-email-identity --email-address you@example.com --region ca-central-1 --profile allergy-tracker
   ```
   AWS emails that address a confirmation link — click it before anything will send.
2. **SES starts in the sandbox.** Until you request production access (not necessary for a
   personal project), SES will only deliver to *verified* recipients too. Verify your own inbox
   the same way if you're both the sender and the test subscriber:
   ```bash
   aws ses verify-email-identity --email-address you@example.com --region ca-central-1 --profile allergy-tracker
   ```
   (Same command — SES treats sender and recipient verification identically; if it's the same
   address you only need to do this once.)
3. Pass the verified sender address as the `SesSenderEmail` parameter on `sam deploy`. The
   template scopes the notify function's SES permission to exactly that one identity ARN, not
   all of SES — a leaked credential still couldn't send as an arbitrary address.
4. Sandbox sending is free and plenty for a personal project (SES itself is ~$0.10/1,000 emails
   either way — see the cost posture note in `IMPLEMENTATION_PLAN.md`). There's no reason to
   request production access unless you plan on real strangers subscribing.

## AWS credentials for local runs

Avoid creating long-lived IAM access keys if you can. Use IAM Identity Center (SSO) instead:

```bash
aws configure sso        # one-time
aws sso login --profile allergy-tracker
export AWS_PROFILE=allergy-tracker
```

SSO credentials expire on their own, so a leaked `~/.aws` directory is a bounded problem rather
than a permanent one.

## CI/CD one-time setup (Phase 6) — done, kept here for redoing in a new account

`.github/workflows/ci.yml` runs tests/lint on every PR and push, and deploys both stacks on
every push to `main`. Two things needed doing by hand, once, before the deploy jobs would work —
neither is something CI should do to itself. Both are done for this account/repo; the steps below
are what to redo if this project is ever forked or moved to a different AWS account.

1. **Deploy the GitHub OIDC role** (`infra/github-oidc-template.yaml`) — creates the IAM role
   CI assumes, trusted only for this exact repo on `refs/heads/main`, so a PR from a fork can
   never obtain deploy credentials:
   ```bash
   sam deploy --guided -t infra/github-oidc-template.yaml
   ```
   Take the `RoleArn` output and add it as the **`AWS_DEPLOY_ROLE_ARN`** repo secret (GitHub →
   Settings → Secrets and variables → Actions). If this AWS account already has a GitHub OIDC
   provider from another project, pass its ARN via `--parameter-overrides
   OIDCProviderArn=<existing arn>` instead of letting this template create a second one — IAM
   only allows one per account.

   The trust condition matches GitHub's OIDC `sub` claim **exactly**, including the immutable
   numeric org/repo IDs GitHub embeds alongside the names (`repo:{org}@{orgId}/{repo}@{repoId}
   :ref:refs/heads/main`) — a `StringLike` match on names alone stopped working once GitHub added
   this. Pass your own via the `GitHubOrgId`/`RepositoryId` template parameters, found with:
   ```bash
   gh api users/<org> --jq .id        # or orgs/<org> for a GitHub org, not a personal account
   gh api repos/<org>/<repo> --jq .id
   ```

2. **Point `s3_bucket` at the SAM-managed artifacts bucket explicitly.** `infra/samconfig-
   backend.toml` and `infra/samconfig-hosting.toml` set `s3_bucket = "<bucket name>"` rather than
   `resolve_s3 = true`. `resolve_s3` asks the SAM CLI to look up (or create) the bucket at deploy
   time, which needs broader S3 permissions than the CI role deliberately has — the least-
   privilege deploy role in `infra/github-oidc-template.yaml` is scoped to exactly one named
   bucket. Find the bucket once (`aws s3 ls | grep aws-sam-cli-managed-default-
   samclisourcebucket`) and pin it in both `samconfig-*.toml` files and as the
   `SamArtifactsBucketName` parameter when deploying the OIDC template.

3. **Add a lifecycle rule to that bucket**, since neither `sam deploy` nor CloudFormation deletes
   old build zips on their own — left alone that grows forever:
   ```bash
   BUCKET=$(aws s3 ls | grep aws-sam-cli-managed-default-samclisourcebucket | awk '{print $3}')
   aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration '{
     "Rules": [{
       "ID": "expire-old-build-artifacts",
       "Status": "Enabled",
       "Filter": {},
       "Expiration": {"Days": 30},
       "NoncurrentVersionExpiration": {"NoncurrentDays": 30}
     }]
   }'
   ```

With all three done, a push to `main` builds/tests, deploys the backend stack, then rebuilds the
dashboard against the live `ApiEndpoint` and syncs it to the hosting bucket — see the `deploy-*`
jobs in `.github/workflows/ci.yml`. Both jobs have gone green end to end; see
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) Phase 6 for the debugging history behind steps
1 and 2 above.
