import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
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
      "/org": backend,
      "/analytics": backend,
      "/ws": { target: backend, ws: true },
    },
  },
});
