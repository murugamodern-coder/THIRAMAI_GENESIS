import { useEffect, useLayoutEffect, useRef } from "react";

import { logEvent } from "./telemetry.js";

const PERF = typeof import.meta !== "undefined" && import.meta.env?.VITE_CC_PERF === "1";
const THRESH_MS = Number(typeof import.meta !== "undefined" ? import.meta.env?.VITE_CC_PERF_RENDER_MS ?? 50 : 50);

/**
 * Logs layout→paint cost per commit when slow or VITE_CC_PERF=1.
 * Use sparingly on heavy pages (non-blocking).
 */
export function useRenderTiming(componentName) {
  const t0 = useRef(0);
  /* Measure each commit: layout start → post-paint. */
  useLayoutEffect(() => {
    if (typeof performance !== "undefined") {
      t0.current = performance.now();
    }
  });
  useEffect(() => {
    if (typeof performance === "undefined") return;
    const ms = performance.now() - t0.current;
    if (PERF || ms >= THRESH_MS) {
      logEvent("perf_render", {
        component: componentName,
        commitToPaintMs: Math.round(ms * 10) / 10,
      });
    }
  });
}
