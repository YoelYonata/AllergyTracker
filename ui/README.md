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
- `src/icons.tsx` -- hand-drawn SVG icons per allergen (tree/grass/weed) plus the brand logo mark,
  colored via `theme.ts` so icon color always matches the chart's series color for that type
- `src/components/` -- `LocationPicker`, `TodaySummary`, `TrendChart` (Recharts), `SubscribeForm`

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

Hosting (Phase 6): S3 + CloudFront, per the cost posture note in
`docs/IMPLEMENTATION_PLAN.MD`. Not deployed yet -- `npm run build` + manual S3 sync until the
CI job exists.
