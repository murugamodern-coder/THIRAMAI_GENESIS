import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import "./styles/cc-theme.css";
import App from "./App.jsx";
import ToastHost from "./components/ToastHost.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { ThemeProvider } from "./context/ThemeContext.jsx";
import { ccHookDebugEnabled } from "./lib/hookDebug.js";
import { initTelemetry } from "./lib/telemetry.js";
import TelemetryNavigation from "./components/TelemetryNavigation.jsx";
import HealthGate from "./components/HealthGate.jsx";

initTelemetry();

if (typeof window !== "undefined" && ccHookDebugEnabled()) {
  console.debug("[cc:bootstrap]", {
    hash: window.location.hash,
    ua: navigator.userAgent,
  });
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ThemeProvider>
      <HashRouter>
        <TelemetryNavigation />
        <ErrorBoundary boundaryName="root">
          <HealthGate>
            <a className="cc-skip-link" href="#cc-main-content">
              Skip to main content
            </a>
            <App />
            <ToastHost />
          </HealthGate>
        </ErrorBoundary>
      </HashRouter>
    </ThemeProvider>
  </StrictMode>,
);

