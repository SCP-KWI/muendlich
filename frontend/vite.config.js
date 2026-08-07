import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// In production nginx maps /handbuch to the handbuch.html in the web root (see
// nginx.conf). The dev server serves public/ verbatim, so without this the help
// button would 404 under `npm run dev` and work only once deployed.
const handbuchRoute = {
  name: "handbuch-route",
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url === "/handbuch") req.url = "/handbuch.html";
      next();
    });
  },
};

// The dev server proxies /api to the backend so the PWA and API share an origin.
export default defineConfig({
  plugins: [
    react(),
    handbuchRoute,
    VitePWA({
      registerType: "autoUpdate",
      // Precache fonts too, so the app is fully usable offline (default globs
      // exclude woff2).
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,woff2,webmanifest}"],
        // The handbook is ~1 MB of inlined screenshots. Precaching it would
        // put that into every install; it is a reference document, fetched
        // on demand.
        globIgnores: ["**/handbuch.html"],
        // …and the service worker must not answer /handbuch from the app
        // shell. generateSW routes *every* navigation to index.html, so
        // without this the help button opens a second copy of the app: the
        // request is served from the cache and never reaches nginx. Invisible
        // to curl and to a fresh browser profile — it only appears once the
        // worker is installed, which is every returning user.
        navigateFallbackDenylist: [/^\/handbuch$/],
      },
      manifest: {
        name: "muendlich",
        short_name: "muendlich",
        description: "Capture post-lesson observations by voice",
        lang: "de",
        theme_color: "#2c5f7c",
        background_color: "#ffffff",
        display: "standalone",
        icons: [
          {
            src: "icon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "any maskable",
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
