import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import "./styles/cc-theme.css";
import App from "./App.jsx";
import ToastHost from "./components/ToastHost.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <HashRouter>
      <ErrorBoundary>
        <App />
        <ToastHost />
      </ErrorBoundary>
    </HashRouter>
  </StrictMode>,
);

/* PWA: register service worker in production (same origin /static/command_center/) */
if (import.meta.env.PROD && typeof window !== "undefined" && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    const base = import.meta.env.BASE_URL || "/static/command_center/";
    const swUrl = new URL("sw.js", `${window.location.origin}${base}`).href;
    navigator.serviceWorker.register(swUrl, { scope: base }).catch(() => {});
  });
}
