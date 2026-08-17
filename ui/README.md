UI (ui/)
=======

React + TypeScript SPA (Vite) that visualizes today's pollen for a location, shows a trend
chart, and lets users subscribe for alerts. Talks only to the Phase 4 Read API
(`services/src/api/`) -- never touches DynamoDB directly.

Layout:
- `src/api.ts` -- typed fetch wrapper for the four read/subscribe routes
- `src/types.ts` -- response shapes, mirrors what `api.handler.py` actually returns
- `src/theme.ts` -- the three pollen-type colors (validated categorical palette) and
  light/dark chrome tokens
- `src/components/` -- `LocationPicker`, `TodaySummary`, `TrendChart` (Recharts), `SubscribeForm`

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

Hosting (Phase 6): S3 + CloudFront, per the cost posture note in
`docs/IMPLEMENTATION_PLAN.MD`. Not deployed yet -- `npm run build` + manual S3 sync until the
CI job exists.
