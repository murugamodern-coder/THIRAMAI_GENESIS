import React from "react";

import { clearAuthStorage } from "../api/client.js";
import { parseFailingComponentFrame } from "../lib/errorBoundaryUtils.js";
import { captureUiError } from "../lib/telemetry.js";

const CRASH_STORAGE_KEY = "thiramai_cc_last_ui_crash";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    const frame = parseFailingComponentFrame(errorInfo?.componentStack || "");
    const boundaryName = this.props.boundaryName || "ErrorBoundary";
    const payload = {
      boundary: boundaryName,
      failingComponent: frame?.name || null,
      failingFrame: frame?.raw || null,
      message: error?.message || String(error),
      stack: error?.stack || null,
      componentStack: errorInfo?.componentStack || null,
    };
    captureUiError(error, {
      boundary: boundaryName,
      failingComponent: frame?.name || null,
      componentStackHead: (errorInfo?.componentStack || "").split("\n").slice(0, 12).join("\n"),
    });
    try {
      if (typeof sessionStorage !== "undefined") {
        sessionStorage.setItem(
          CRASH_STORAGE_KEY,
          JSON.stringify({
            t: new Date().toISOString(),
            boundary: boundaryName,
            failingComponent: frame?.name || null,
            message: payload.message,
            stackHead: (payload.stack || "").split("\n").slice(0, 8).join("\n"),
            componentStackHead: (payload.componentStack || "").split("\n").slice(0, 12).join("\n"),
          }),
        );
      }
    } catch {
      /* ignore quota / private mode */
    }
    this.setState({ error, errorInfo });
  }

  render() {
    if (this.state.hasError) {
      const isDev = typeof import.meta !== "undefined" && import.meta?.env?.DEV;
      const em = this.state.error?.message || String(this.state.error || "");
      const isAuthError = /\b(401|403)\b|unauthori[sz]ed|forbidden/i.test(em);
      const showHookDetails =
        isDev || /310|hooks|Rendered more hooks/i.test(em);
      const firstName = parseFailingComponentFrame(this.state.errorInfo?.componentStack || "")?.name;
      return (
        <div
          className="cc-card"
          role="alert"
          aria-live="assertive"
          style={{
            minHeight: "40vh",
            maxWidth: 720,
            margin: "24px auto",
            padding: 24,
          }}
        >
          <h2 style={{ marginTop: 0 }}>{isAuthError ? "Session expired" : "Something went wrong"}</h2>
          <p className="cc-muted" style={{ marginTop: -8 }}>
            {isAuthError
              ? "Session expired, please login again."
              : "A UI component crashed. The rest of the shell stays up — reload to fully recover."}
          </p>
          {firstName ? (
            <p style={{ fontSize: 13, fontWeight: 600 }}>
              First frame: <code>{firstName}</code>
            </p>
          ) : null}
          {showHookDetails && (
            <details style={{ marginBottom: 12 }}>
              <summary className="cc-muted" style={{ cursor: "pointer" }}>
                {isDev ? "Error details (dev)" : "Error details (hooks / #310)"}
              </summary>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {`message: ${em}
firstFrame: ${firstName || "n/a"}
stack: ${this.state.error?.stack || "n/a"}
componentStack:
${this.state.errorInfo?.componentStack || "n/a"}`}
              </pre>
            </details>
          )}
          {isAuthError ? (
            <button
              type="button"
              className="cc-btn cc-btn-primary"
              onClick={() => {
                clearAuthStorage();
                window.location.hash = "#/login";
              }}
            >
              Login
            </button>
          ) : (
            <button
              type="button"
              className="cc-btn cc-btn-primary"
              onClick={() => window.location.reload()}
            >
              Reload page
            </button>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}
