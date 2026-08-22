import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // The deployed API's CORS policy allows exactly one origin (the CloudFront domain), so a
  // browser on http://localhost:5173 can't call it directly. In dev we therefore point the app
  // at a same-origin /api prefix and let Vite proxy it through -- the proxy runs in Node, not
  // the browser, so CORS never applies. Production is unaffected: `npm run build` uses the real
  // VITE_API_BASE_URL and talks to the API directly from the allowed CloudFront origin.
  // '.' rather than process.cwd(): this file is type-checked by `tsc -b` without @types/node,
  // so the `process` global isn't available here. Vite resolves the path against the cwd anyway.
  const env = loadEnv(mode, '.', '')
  const proxyTarget = env.VITE_DEV_API_PROXY_TARGET

  return {
    plugins: [react()],
    server: {
      proxy: proxyTarget
        ? {
            '/api': {
              target: proxyTarget,
              changeOrigin: true,
              rewrite: (path) => path.replace(/^\/api/, ''),
            },
          }
        : undefined,
    },
  }
})
