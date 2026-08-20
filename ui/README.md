UI (ui/)
=======

React + TypeScript SPA (Vite) that visualizes today's pollen for a location, shows a trend
chart with a 30/90-day range toggle, and lets users subscribe for alerts. Talks only to the
Phase 4 Read API (`services/src/api/`) -- never touches DynamoDB directly.

Layout:
- `src/api.ts` -- typed fetch wrapper for the four read/subscribe routes
- `src/types.ts` -- response shapes, mirrors what `api.handler.py` actually returns
- `src/theme.ts` -- the three pollen-type colors (validated categorical palette) and
  light/dark chrome tokens
- `src/icons.tsx` -- hand-drawn SVG icons per allergen (tree/grass/weed) plus the brand logo mark,
  colored via `theme.ts` so icon color always matches the chart's series color for that type
- `src/components/` -- `LocationPicker`, `TodaySummary`, `TrendChart` (Recharts, with the 30d/90d
  range toggle), `SubscribeForm`

Brand: a gold/amber accent (`--brand` in `index.css`) is its own slot in the same validated color
system the chart uses, chosen so it never collides with the three series colors. Swap it in one
place (the `--brand`/`--brand-ink` custom properties) if you want a different accent later.

Local dev:
```
npm install
cp .env.example .env.local   # fill in VITE_API_BASE_URL (from `sam deploy` output: ApiEndpoint)
npm run dev
```

Build:
```
npm run build     # outputs to dist/, ready to sync to S3
```

Hosting: **live at https://d3myi08baazbck.cloudfront.net** -- S3 + CloudFront, stack defined in
`infra/hosting-template.yaml` (separate from the backend stack, see `docs/TEARDOWN.md`). A push
to `main` rebuilds and redeploys this automatically (`deploy-frontend` in
`.github/workflows/ci.yml`); the commands below are only needed for a manual/local redeploy:

```
npm run build
aws s3 sync dist/ s3://<BucketName from the hosting stack output> --delete --profile allergy-tracker
```

CloudFront caches aggressively; if a change doesn't show up, invalidate:
```
aws cloudfront create-invalidation --distribution-id <DistributionId> --paths "/*" --profile allergy-tracker
```
