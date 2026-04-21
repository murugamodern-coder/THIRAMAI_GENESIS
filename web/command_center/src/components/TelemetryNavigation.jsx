import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

import { logEvent } from "../lib/telemetry.js";

/** HashRouter-safe navigation / virtual page views. Renders null. */
export default function TelemetryNavigation() {
  const location = useLocation();
  const first = useRef(true);

  useEffect(() => {
    const path = `${location.pathname || ""}${location.search || ""}`;
    logEvent("page_view", {
      path,
      key: location.key,
      hash: typeof window !== "undefined" ? window.location.hash : "",
      initial: first.current,
    });
    first.current = false;
  }, [location.pathname, location.search, location.key]);

  return null;
}
