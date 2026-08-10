import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// FastAPI's host port, published by docker-compose so the dev server can reach
// it without going through nginx. docker-compose.dev.yml overrides it with the
// compose service name, where the published port is not the way in.
const API = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

// Set only when Vite is reached *through* something else — docker-compose.dev
// puts nginx on :8080 in front of it. The HMR websocket is opened by the
// browser, so it must be told the port the browser can see; left to itself
// Vite advertises its own, and the page loads once and then never updates.
const HMR_CLIENT_PORT = process.env.VITE_HMR_CLIENT_PORT

// The dev server stands in for nginx: it decides which paths belong to FastAPI
// and serves index.html for everything else. Production repeats this split in
// nginx/nginx.conf — the two must stay in step, or a route works in one and
// dead-ends in the other.
export default defineConfig({
  plugins: [react()],

  server: {
    host: true,
    port: 5173,
    ...(HMR_CLIENT_PORT ? { hmr: { clientPort: Number(HMR_CLIENT_PORT) } } : {}),
    proxy: {
      // Anchored for the same reason as /m below: the bare prefix '/api' also
      // matches /apifoo, which nginx's `~ ^/api(/|$)` does not.
      '^/api(/|$)': { target: API, changeOrigin: true },

      // The QR destination. FastAPI answers it with a 302 to /r/:token, and the
      // proxy must hand that redirect to the browser rather than following it
      // itself: the address bar has to change, because the SPA is then loaded
      // fresh at the new path and reads its token from there. `followRedirects`
      // defaults to false — stated explicitly because silently flipping it
      // would break the flow in a way that looks like a backend bug.
      // Anchored regex, not the bare prefix '/m': a prefix also matches /mfoo,
      // which nginx's `~ ^/m(/|$)` does not. The two must agree or a path is
      // proxied in development and served as the SPA in production.
      '^/m(/|$)': { target: API, changeOrigin: true, followRedirects: false },

      // `/r` is deliberately absent. It belongs to the SPA fallback, which
      // serves index.html for any path Vite does not recognise as a file.
    },
  },

  test: {
    environment: 'jsdom',
    // .tsx as well: component tests are where the constraints that actually
    // break this product live.
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
