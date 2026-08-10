# Data model (DynamoDB)

Single-table design. One table, `allergy-tracker`, holds pollen readings, subscribers, and the
list of locations to track. This is the idiomatic DynamoDB approach: you model around your
**access patterns**, not around entities the way you would in a relational schema.

## Access patterns

These drove the key design. Every one is a single `Query` or `GetItem` — no `Scan` anywhere.

| # | Access pattern | Used by | How |
|---|----------------|---------|-----|
| 1 | Get all locations to ingest | Ingestion job | `Query pk = "CONFIG#LOCATIONS"` |
| 2 | Get today's reading for a location | Dashboard "today" view | `GetItem pk = "LOC#<id>", sk = "READING#<date>"` |
| 3 | Get last N days for a location | Dashboard trend chart | `Query pk = "LOC#<id>" AND sk BETWEEN "READING#<from>" AND "READING#<to>"` |
| 4 | Get all subscribers for a location | Notifier | `Query pk = "LOC#<id>" AND begins_with(sk, "SUB#")` |
| 5 | Get all subscriptions for an email | Unsubscribe / manage prefs | `Query GSI1 gsi1pk = "EMAIL#<email>"` |

Pattern 3 works because ISO dates (`2026-08-10`) sort lexicographically in the same order they
sort chronologically. That's why the sort key uses `READING#YYYY-MM-DD` and not, say, a
`MM/DD/YYYY` format — the range query would be meaningless.

## Table definition

- **Table name:** `allergy-tracker`
- **Partition key:** `pk` (String)
- **Sort key:** `sk` (String)
- **Billing mode:** `PAY_PER_REQUEST` (on-demand — no capacity planning, and effectively free at
  this project's volume)
- **TTL attribute:** `ttl` (Number, epoch seconds) — set on readings only, so old history expires
  automatically instead of growing forever
- **Streams:** `NEW_AND_OLD_IMAGES` — enabled so Phase 3 can optionally drive the notifier off
  the stream instead of calling SES inline

### GSI1 — email lookup

- **Partition key:** `gsi1pk` (String)
- **Sort key:** `gsi1sk` (String)
- **Projection:** `ALL`

Only subscriber items carry `gsi1pk`/`gsi1sk`, which makes this a **sparse index** — readings and
config items never appear in it, so the index stays small and cheap.

## Item types

### Location config

Tells the ingestion job what to fetch. Seeded manually (or by a small script) rather than through
the app.

```
pk    = "CONFIG#LOCATIONS"
sk    = "LOC#vancouver"
```

| Attribute | Type | Example | Notes |
|-----------|------|---------|-------|
| `entity` | S | `"LOCATION"` | Item-type discriminator |
| `location_id` | S | `"vancouver"` | Slug; used in `LOC#<id>` keys |
| `display_name` | S | `"Vancouver, BC"` | Shown in the dashboard |
| `latitude` | N | `49.2827` | Passed to the Pollen API |
| `longitude` | N | `-123.1207` | Passed to the Pollen API |
| `enabled` | BOOL | `true` | Lets you pause a location without deleting it |

### Pollen reading

**One item per location per date**, with all pollen types stored in a single map — not one item
per pollen type. The dashboard always displays grass/tree/weed together, so splitting them would
mean three reads (or a wider query) for every view with nothing gained. Item size stays a few KB,
far under the 400 KB limit.

```
pk    = "LOC#vancouver"
sk    = "READING#2026-08-10"
```

| Attribute | Type | Example | Notes |
|-----------|------|---------|-------|
| `entity` | S | `"READING"` | |
| `location_id` | S | `"vancouver"` | |
| `date` | S | `"2026-08-10"` | The **forecast** date, not the fetch date |
| `region_code` | S | `"CA"` | From the API response |
| `types` | M | see below | Keyed by pollen type code |
| `max_upi` | N | `4` | Highest UPI across all types — denormalized so the anomaly check and dashboard don't have to walk the map |
| `fetched_at` | S | `"2026-08-10T06:00:11Z"` | When this was last written |
| `ttl` | N | `1786000000` | Epoch seconds; ~1 year out |

The `types` map:

```json
{
  "GRASS": { "display_name": "Grass", "in_season": true,  "upi": 4, "category": "High" },
  "TREE":  { "display_name": "Tree",  "in_season": false, "upi": 1, "category": "Very Low" },
  "WEED":  { "display_name": "Weed",  "in_season": true,  "upi": 2, "category": "Low" }
}
```

`upi` is Google's **Universal Pollen Index**, 0–5. It is the field the anomaly check keys on.
It can be absent (stored as `null`) when the API has no coverage for that type at that location —
the threshold check must skip nulls rather than treating them as 0.

**Why keyed on forecast date:** the Google API returns up to 5 days ahead, so each fetch writes
several items. Re-fetching the same date overwrites it with a fresher forecast, which makes the
whole job **idempotent** — you can re-run it freely without creating duplicates. The trade-off is
that you keep only the latest forecast per date, not the history of how a forecast changed. That's
the right call here; if you ever want forecast-drift history, add the fetch date to the sort key
(`READING#<forecast_date>#<fetched_date>`).

### Subscriber

```
pk      = "LOC#vancouver"
sk      = "SUB#user@example.com"
gsi1pk  = "EMAIL#user@example.com"
gsi1sk  = "LOC#vancouver"
```

| Attribute | Type | Example | Notes |
|-----------|------|---------|-------|
| `entity` | S | `"SUBSCRIBER"` | |
| `email` | S | `"user@example.com"` | |
| `location_id` | S | `"vancouver"` | |
| `threshold` | N | `3` | Alert when any watched type's UPI is `>=` this |
| `pollen_types` | SS | `["GRASS","TREE"]` | Empty/absent means "all types" |
| `status` | S | `"CONFIRMED"` | `PENDING` → `CONFIRMED` → `UNSUBSCRIBED` |
| `unsubscribe_token` | S | `"a3f9..."` | Random token for one-click unsubscribe links |
| `created_at` | S | `"2026-08-01T12:00:00Z"` | |
| `last_notified_date` | S | `"2026-08-09"` | Dedup guard — see below |

**`last_notified_date` matters more than it looks.** The ingestion job runs every few hours, so a
day with high pollen would fire an alert on every run. Before sending, the notifier does a
conditional update:

```
UpdateExpression:    SET last_notified_date = :today
ConditionExpression: attribute_not_exists(last_notified_date) OR last_notified_date < :today
```

If the condition fails, another run already sent today's email and this one skips. Doing the
claim *before* sending — and letting DynamoDB arbitrate — is what keeps duplicate emails from
racing, rather than checking-then-sending as two separate steps.

## What this buys you

The single-table design means the notifier's "give me every subscriber for the location that just
breached" is one query against a partition you already have the key for. In a relational schema
that's a join; here it's the physical layout of the table. That's the core DynamoDB idea worth
taking away from this project — and the reason the key names are generic (`pk`/`sk`) rather than
`location_id`/`timestamp`: the same two attributes mean different things depending on the item type.
