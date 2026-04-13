import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://127.0.0.1:8000";
/** Bust browser/CDN caches for fixed filenames (cc-app.js / cc-index.css). */
const CACHE_BUST = process.env.CC_BUILD_ID || Date.now().toString(36);

export default defineConfig({
  plugins: [
    react(),
    {
      name: "command-center-cache-bust",
      transformIndexHtml(html) {
        return html
          .replace(/cc-app\.js(?!\?)/g, `cc-app.js?v=${CACHE_BUST}`)
          .replace(/cc-index\.css(?!\?)/g, `cc-index.css?v=${CACHE_BUST}`);
      },
    },
  ],
  base: "/static/command_center/",
  build: {
    outDir: "../../static/command_center",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "cc-app.js",
        chunkFileNames: "cc-[name].js",
        assetFileNames: "cc-[name][extname]",
      },
    },
  },
  server: {
    proxy: {
      "/auth": backend,
      "/chat": backend,
      "/me": backend,
      "/dashboard": backend,
      "/inventory": backend,
      "/billing": backend,
      "/production": backend,
      "/personal": backend,
      "/life": backend,
      "/org": backend,
      "/analytics": backend,
      "/integrations": backend,
      "/push": backend,
      "/auth/google": backend,
      "/ws": { target: backend, ws: true },
    },
  },
});
