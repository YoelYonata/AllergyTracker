UI (ui/)
=======

Purpose: static SPA to visualize today's pollen for a location and show trend charts, and allow users to subscribe for alerts.

Suggested layout:
- ui/src/             # React app (Vite recommended)
- ui/package.json

Features:
- Location selector
- Today's summary panel and pollen types
- Trend chart (charting: Chart.js, Recharts, or ApexCharts)
- Subscription form (email capture + threshold selection)

Hosting:
- Host as static site on Netlify, Vercel, or S3 + CloudFront.

Local dev:
- npm install
- npm run dev