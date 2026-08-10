# Configuration & secrets

## Where the Google Pollen API key goes

**Never commit the key.** `.env` and `.env.*` are already in `.gitignore`; keep it that way.

The code resolves the key in this order, so the same handler works locally and in Lambda without
branching on environment:

1. `GOOGLE_POLLEN_API_KEY` environment variable — **local development only**
2. `POLLEN_API_KEY_PARAM` environment variable, naming an **SSM Parameter Store** parameter that
   holds the key — **the AWS path**

### Local development

Create `services/src/ingest/.env` (gitignored):

```
GOOGLE_POLLEN_API_KEY=AIza...your-key...
DDB_TABLE_NAME=allergy-tracker
```

The handler loads it via `python-dotenv` if that package is installed. Nothing else to do.

### On AWS — use SSM Parameter Store (SecureString)

Store the key once, from your own machine:

```bash
aws ssm put-parameter \
  --name /allergy-tracker/google-pollen-api-key \
  --value "AIza...your-key..." \
  --type SecureString \
  --overwrite
```

Then point the Lambda at the *parameter name*, not the value:

```
POLLEN_API_KEY_PARAM=/allergy-tracker/google-pollen-api-key
```

The Lambda fetches it with `WithDecryption=True` on cold start and caches it in a module-level
variable, so warm invocations don't re-call SSM. The SAM template grants the function only
`ssm:GetParameter` on that one parameter path, plus `kms:Decrypt` on the default SSM key.

**Why not just a plain Lambda environment variable?** Lambda env vars are encrypted at rest, but
the plaintext value is visible to anyone who can call `lambda:GetFunctionConfiguration` or open the
console — and, more practically, you'd end up putting it in the SAM template to deploy it, which
puts your key straight into git. Parameter Store keeps the secret and the deployable config
separate. That separation is the actual point, not the encryption.

**SSM Parameter Store vs. Secrets Manager:** Secrets Manager adds built-in rotation and
cross-account sharing for about **$0.40/secret/month**. Parameter Store SecureString is **free** at
the standard tier and does everything this project needs. Use Parameter Store here; reach for
Secrets Manager when you need automatic rotation (typically database credentials).

### Restrict the key in Google Cloud too

Defense in depth — do this even though the key is stored safely:

1. Google Cloud Console → **APIs & Services → Credentials** → your key
2. **API restrictions** → *Restrict key* → select **Pollen API** only. If the key leaks it can't be
   used against other billable Google APIs.
3. Skip **Application restrictions** (IP-based): Lambda's outbound IPs are dynamic, so an IP
   allowlist won't work unless you put the function in a VPC behind a NAT Gateway with an Elastic
   IP — which costs about $32/month and isn't worth it here.
4. Set a **quota limit** on the Pollen API so a leaked key can't run up a large bill.

## Environment variables

| Variable | Where | Required | Purpose |
|----------|-------|----------|---------|
| `GOOGLE_POLLEN_API_KEY` | Local only | One of these two | The API key, in plaintext |
| `POLLEN_API_KEY_PARAM` | Lambda | One of these two | SSM parameter name holding the key |
| `DDB_TABLE_NAME` | Both | Yes | DynamoDB table name (default `allergy-tracker`) |
| `FORECAST_DAYS` | Both | No | Days to fetch, 1–5 (default `3`) |
| `READING_TTL_DAYS` | Both | No | How long readings live before TTL expiry (default `365`) |
| `AWS_REGION` | Both | Yes | Set automatically inside Lambda |

## AWS credentials for local runs

Don't create long-lived access keys if you can avoid it. Use IAM Identity Center (SSO):

```bash
aws configure sso        # one-time
aws sso login --profile allergy-tracker
export AWS_PROFILE=allergy-tracker
```

The credentials expire on their own, so a leaked `~/.aws` directory is a bounded problem rather
than a permanent one.
