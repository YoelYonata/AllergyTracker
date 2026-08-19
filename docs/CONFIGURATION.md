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
| `READING_TTL_DAYS` | Ingest only | No (default `365`) | How long readings live before TTL expiry |
| `DEFAULT_THRESHOLD` | Notify + api | No (default `3`) | Fallback UPI threshold if a subscriber has none set |
| `SES_SENDER_EMAIL` | Notify + api | Yes | Verified SES identity used as the "From" address on alert and confirmation emails |
| `CONFIRM_BASE_URL` | Api Lambda, and local `seed_subscriber.py` | Yes, to subscribe | The deployed `ConfirmFunction`'s Function URL. The template wires this into the api Lambda automatically; only set it by hand for local script runs — see the stack Outputs after `sam deploy` |

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
| `GET /pollen/{location}/history?days=N` | Trend data; `days` defaults to 14, max 30 |
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

## CI/CD one-time setup (Phase 6)

`.github/workflows/ci.yml` runs tests/lint on every PR and push, and deploys both stacks on
every push to `main`. Two things need doing by hand, once, before the deploy jobs will work —
neither is something CI should do to itself:

1. **Deploy the GitHub OIDC role** (`infra/github-oidc-template.yaml`) — creates the IAM role
   CI assumes, trusted only for `repo:<org>/<repo>:ref:refs/heads/main`, so a PR from a fork can
   never obtain deploy credentials:
   ```bash
   sam deploy --guided -t infra/github-oidc-template.yaml
   ```
   Take the `RoleArn` output and add it as the **`AWS_DEPLOY_ROLE_ARN`** repo secret (GitHub →
   Settings → Secrets and variables → Actions). If this AWS account already has a GitHub OIDC
   provider from another project, pass its ARN via `--parameter-overrides
   OIDCProviderArn=<existing arn>` instead of letting this template create a second one — IAM
   only allows one per account.

2. **Add a lifecycle rule to the SAM-managed artifacts bucket.** `sam deploy --resolve-s3`
   (used by both `infra/samconfig-backend.toml` and `infra/samconfig-hosting.toml`) uploads a
   new build zip to this bucket on every deploy but never deletes old ones — left alone that
   grows forever. One-time fix:
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

Once both are done, a push to `main` builds/tests, deploys the backend stack, then rebuilds the
dashboard against the live `ApiEndpoint` and syncs it to the hosting bucket — see the `deploy-*`
jobs in `.github/workflows/ci.yml`.
