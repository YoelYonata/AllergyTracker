# Data model (DynamoDB)

Single-table design: one table, `allergy-tracker`, holds pollen readings, subscribers, and the
list of locations to track. DynamoDB rewards modeling around **access patterns** rather than
around entities the way a relational schema would, so the patterns below drove the key design,
not the other way around.

## Access patterns

Every one of these is a single `Query` or `GetItem` — no `Scan`.

| # | Access pattern | Used by | How |
|---|----------------|---------|-----|
| 1 | Get all locations to ingest | Ingestion job | `Query pk = "CONFIG#LOCATIONS"` |
| 2 | Get today's reading for a location | Dashboard "today" view | `GetItem pk = "LOC#<id>", sk = "READING#<date>"` |
| 3 | Get last N days for a location | Dashboard trend chart | `Query pk = "LOC#<id>" AND sk BETWEEN "READING#<from>" AND "READING#<to>"` |
| 4 | Get confirmed subscribers for a location | Notifier | `Query pk = "LOC#<id>" AND begins_with(sk, "SUB#")` |
| 5 | Get all subscriptions for an email | Unsubscribe / manage prefs | `Query GSI1 gsi1pk = "EMAIL#<email>"` |

Pattern 3 relies on ISO dates (`2026-08-10`) sorting lexicographically in the same order they sort
chronologically — that's why the sort key is `READING#YYYY-MM-DD` and not, say, `MM/DD/YYYY`.

## Table definition

- **Table name:** `allergy-tracker`
- **Partition key:** `pk` (String) · **Sort key:** `sk` (String)
- **Billing mode:** `PAY_PER_REQUEST` — no capacity planning, and effectively free at this
  project's volume (see the cost posture note in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)).
- **TTL attribute:** `ttl` (epoch seconds), set on reading items only — old history expires
  automatically instead of growing forever.
- **Streams:** `NEW_AND_OLD_IMAGES`, enabled so Phase 3 can optionally drive the notifier off the
  stream instead of calling SES inline.

### GSI1 — email lookup

- **Partition key:** `gsi1pk` (String) · **Sort key:** `gsi1sk` (String) · **Projection:** `ALL`

Only subscriber items carry `gsi1pk`/`gsi1sk` — a **sparse index**, so readings and config items
never land in it and the index stays small.

## Item types

### Location config

Tells the ingestion job what to fetch. Seeded with `scripts/seed_locations.py` rather than
through the app.

```
pk = "CONFIG#LOCATIONS"
sk = "LOC#vancouver"
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

**One item per location per forecast date**, with every pollen type in a single map rather than
one item per type. The dashboard always shows grass/tree/weed together, so splitting them would
mean three reads for every view with nothing gained; item size stays a few KB either way, far
under the 400 KB limit.

```
pk = "LOC#vancouver"
sk = "READING#2026-08-10"
```

| Attribute | Type | Example | Notes |
|-----------|------|---------|-------|
| `entity` | S | `"READING"` | |
| `location_id` | S | `"vancouver"` | |
| `date` | S | `"2026-08-10"` | The **forecast** date, not the fetch date |
| `region_code` | S | `"CA"` | From the API response |
| `types` | M | see below | Keyed by pollen type code |
| `max_upi` | N | `4` | Highest UPI across all types — denormalized so the anomaly check and dashboard don't have to walk the map |
| `fetched_at` | S | `"2026-08-10T06:00:11Z"` | When this item was last written |
| `ttl` | N | `1786000000` | Epoch seconds, ~1 year out |

The `types` map, confirmed against a real `forecast:lookup` response:

```json
{
  "GRASS": { "display_name": "Grass", "in_season": null, "upi": null, "category": null },
  "TREE":  { "display_name": "Tree",  "in_season": true,  "upi": 0,   "category": "None" },
  "WEED":  { "display_name": "Weed",  "in_season": false, "upi": 1,   "category": "Very Low" }
}
```

`upi` is Google's **Universal Pollen Index**, 0–5, and is what the anomaly check keys on. The API
omits `indexInfo` entirely when it has no coverage for a type at a location (the `GRASS` entry
above, in real responses for this location) — that comes through as `upi: null`, and the threshold
check must skip nulls rather than treat them as 0. The raw response also includes a `plantInfo`
array (per-species detail like `MAPLE`, `ELM`) that the ingestion client doesn't store — the
dashboard only needs the three aggregate pollen types, and the fetch requests
`plantsDescription: 0` to keep the payload smaller.

**Why keyed on forecast date:** the API returns up to 5 days ahead, so each fetch writes several
items. Re-fetching the same date overwrites it with a fresher forecast, which makes the whole job
**idempotent** — safe to re-run without creating duplicates. The trade-off is keeping only the
latest forecast per date, not a history of how the forecast changed; that's the right call here.
If forecast-drift history ever matters, add the fetch date to the sort key
(`READING#<forecast_date>#<fetched_date>`).

### Subscriber

```
pk     = "LOC#vancouver"
sk     = "SUB#user@example.com"
gsi1pk = "EMAIL#user@example.com"
gsi1sk = "LOC#vancouver"
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
high-pollen day would otherwise fire an alert on every run. Before sending, the notifier does a
conditional update:

```
UpdateExpression:    SET last_notified_date = :today
ConditionExpression: attribute_not_exists(last_notified_date) OR last_notified_date < :today
```

If the condition fails, another run already sent today's email and this one skips. Doing the claim
*before* sending, with DynamoDB arbitrating the condition, is what prevents two concurrent runs
from both sending — a read-then-send check would race.

## What this buys you

"Give me every subscriber for the location that just breached" is one `Query` against a partition
you already have the key for — in a relational schema that's a join; here it's the physical layout
of the table. That's the core DynamoDB idea worth taking from this project, and it's also why the
key attributes are generic (`pk`/`sk`) rather than `location_id`/`timestamp`: the same two
attributes mean something different depending on the item type stored under them.
