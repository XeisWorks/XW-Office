import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// PR08: Read-only Product Hub WebUI/PWA. Built as a static bundle and served
// same-origin by xw_office.web.app (FastAPI) - no separate Railway service, no
// CORS configuration needed. See docs/product_hub/PROGRESS.md PR08 for context.
export default defineConfig({
  base: "/app/",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "XW Product Hub",
        short_name: "Product Hub",
        description: "Read-only Produktkatalog, Bestand-Schatten und Sync-Status - XeisWorks Product Hub.",
        theme_color: "#20221f",
        background_color: "#f4f1ea",
        display: "standalone",
        start_url: "/app/",
        scope: "/app/",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // Read-only PWA: cache the app shell/static assets, never cache API
        // responses - product data must always come from the network so stale
        // stock/readiness figures are never shown as if current.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [],
      },
    }),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
