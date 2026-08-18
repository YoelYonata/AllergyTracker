# Teardown

How to fully delete this project's AWS resources if you want to stop it from running/billing.

## What's already watching costs

A Budget named **"My Zero-Spend Budget"** ($1.00/month, alerts at $0.01 actual spend) emails
`yoel.yonata@gmail.com` the moment this project spends anything. That's your early warning. This
doc is the next step after that: how to actually stop it.

## What's in each stack

This project now spans **two CloudFormation stacks**, deployed and torn down independently:

### `allergy-tracker` (backend)

- `AllergyTrackerTable` (DynamoDB) — **deleting this permanently deletes all stored readings and
  subscribers**, see the backup step below
- All four Lambdas (`ingest`, `notify`, `confirm`, `api`) and their IAM roles
- All CloudWatch Log Groups and the `IngestFunctionErrorAlarm`
- The EventBridge schedule, the DynamoDB Stream event source mapping, the Lambda Function URL
- The API Gateway HTTP API and its routes

### `allergy-tracker-ui` (static hosting)

- The S3 bucket holding the built dashboard (`ui/dist/`)
- The CloudFront distribution serving it at `https://d3myi08baazbck.cloudfront.net`
- The Origin Access Control + bucket policy connecting the two

Delete the UI stack independently if you just want to take the live site down without touching
pollen data or subscribers:

```powershell
sam delete --stack-name allergy-tracker-ui --region ca-central-1 --profile allergy-tracker
```

CloudFront distributions take several minutes to delete (same as they do to create) — that's
normal, not a hang.

## Step 1 — optional: back up subscriber data first

Skip this if you don't care about losing the subscriber list (e.g. this was only ever test data).

```powershell
aws dynamodb scan --table-name allergy-tracker --profile allergy-tracker --region ca-central-1 `
  --output json > allergy-tracker-backup-$(Get-Date -Format yyyy-MM-dd).json
```

## Step 2 — delete the backend stack

```powershell
sam delete --stack-name allergy-tracker --region ca-central-1 --profile allergy-tracker
```

This prompts for confirmation, deletes the CloudFormation stack, and offers to also delete the
SAM CLI-managed deployment-artifacts S3 bucket (the one holding old build zips) — say yes to that
too, otherwise it sits there accumulating (small, but non-zero) storage cost forever.

Or non-interactively (no prompts — use once you're sure):

```powershell
sam delete --stack-name allergy-tracker --region ca-central-1 --profile allergy-tracker --no-prompts
sam delete --stack-name allergy-tracker-ui --region ca-central-1 --profile allergy-tracker --no-prompts
```

## Step 3 — clean up what's outside the stack

These were created manually (outside CloudFormation, per `docs/CONFIGURATION.md`), so stack
deletion doesn't touch them. They cost nothing sitting idle, but delete them too if you're walking
away entirely:

```powershell
# The Pollen API key in SSM Parameter Store
aws ssm delete-parameter --name /allergy-tracker/google-pollen-api-key `
  --region ca-central-1 --profile allergy-tracker

# The verified SES sender identity (only if you don't want it verified anymore)
aws ses delete-identity --identity yoel.yonata@gmail.com `
  --region ca-central-1 --profile allergy-tracker
```

Leave the **Budget** in place — it costs nothing and is useful to keep watching even with
everything else gone.

## Step 4 — verify nothing's left running

```powershell
aws cloudformation describe-stacks --stack-name allergy-tracker --region ca-central-1 --profile allergy-tracker
# Should error "does not exist" once deletion completes.

aws lambda list-functions --region ca-central-1 --profile allergy-tracker --query "Functions[?starts_with(FunctionName, 'allergy-tracker')].FunctionName"
# Should return an empty list.
```

## Pausing instead of deleting

If you just want to stop the recurring ingest calls (and therefore alert emails) without losing
data or tearing everything down, e.g. going on vacation, toggle the schedule instead. Costs at
this traffic level are already near-zero either way, so this is really about stopping the emails,
not the cost:

```powershell
aws scheduler get-schedule --name IngestFunctionScheduledIngest --group-name default `
  --region ca-central-1 --profile allergy-tracker
# Copy the output, flip "State" to DISABLED, then:
aws scheduler update-schedule --cli-input-json file://schedule.json `
  --region ca-central-1 --profile allergy-tracker
```

Easier in practice: `aws scheduler list-schedules` to find the name, then toggle it via the
EventBridge Scheduler console instead of hand-editing JSON. Or just run Step 2 if you don't need
the data preserved.
