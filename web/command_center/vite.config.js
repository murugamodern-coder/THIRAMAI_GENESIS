import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";

const __dirname = dirname(fileURLToPath(import.meta.url));
let pkgVersion = "0.0.0";
try {
  pkgVersion = JSON.parse(readFileSync(join(__dirname, "package.json"), "utf8")).version || "0.0.0";
} catch {
  /* ignore */
}
const ccVersion = process.env.CC_BUILD_VERSION || pkgVersion;
const ccGitSha = process.env.CC_GIT_SHA || "unknown";

/** Local API (optional): set VITE_DEV_API=http://127.0.0.1:8000 to use your machine instead of production. */
const devApi = process.env.VITE_DEV_API || "https://app.thiramai.co.in";
const devProxy = { target: devApi, changeOrigin: true, secure: true };

export default defineConfig({
  define: {
    __CC_APP_VERSION__: JSON.stringify(ccVersion),
    __CC_GIT_SHA__: JSON.stringify(ccGitSha),
  },
  plugins: [
    react(),
    ...(process.env.ANALYZE_BUNDLE === "1"
      ? [
          visualizer({
            filename: "bundle-stats.html",
            template: "treemap",
            gzipSize: true,
            brotliSize: true,
          }),
        ]
      : []),
  ],
  base: "/static/command_center/",
  build: {
    /** Set `false` when not debugging stacks (smaller deploy, no .map files). */
    sourcemap: true,
    outDir: "../../static/command_center",
    emptyOutDir: true,
    /** Set `CC_MINIFY=0` for readable stack traces (React #310, etc.); default is esbuild minify. */
    minify: process.env.CC_MINIFY === "0" ? false : "esbuild",
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        /** Content hashes invalidate Docker layers and browser caches when sources change. */
        entryFileNames: "cc-app-[hash].js",
        chunkFileNames: "cc-[name]-[hash].js",
        assetFileNames: "cc-[name]-[hash][extname]",
        manualChunks(id) {
          if (id.includes("node_modules/recharts")) return "vendor-recharts";
          if (id.includes("node_modules/react-router")) return "vendor-router";
          if (id.includes("node_modules/zustand")) return "vendor-state";
          if (id.includes("node_modules")) return "vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    proxy: {
      "/health": devProxy,
      "/auth": devProxy,
      "/api": devProxy,
      "/chat": devProxy,
      "/me": devProxy,
      "/dashboard": devProxy,
      "/inventory": devProxy,
      "/billing": devProxy,
      "/production": devProxy,
      "/personal": devProxy,
      "/life": devProxy,
      "/org": devProxy,
      "/analytics": devProxy,
      "/integrations": devProxy,
      "/push": devProxy,
      "/auth/google": devProxy,
      "/business": devProxy,
      "/brain": devProxy,
      "/execute": devProxy,
      "/mission": devProxy,
      "/ws": { ...devProxy, ws: true },
    },
  },
});
