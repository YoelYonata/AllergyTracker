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
| `FORECAST_DAYS` | Both | No (default `3`) | Days to fetch per run, 1–5 |
| `READING_TTL_DAYS` | Both | No (default `365`) | How long readings live before TTL expiry |

## AWS credentials for local runs

Avoid creating long-lived IAM access keys if you can. Use IAM Identity Center (SSO) instead:

```bash
aws configure sso        # one-time
aws sso login --profile allergy-tracker
export AWS_PROFILE=allergy-tracker
```

SSO credentials expire on their own, so a leaked `~/.aws` directory is a bounded problem rather
than a permanent one.
