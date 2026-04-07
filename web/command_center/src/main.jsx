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
