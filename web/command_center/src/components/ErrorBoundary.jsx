import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.error("UI Crash:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="cc-card">
          <h2>Something went wrong</h2>
          <p className="cc-muted" style={{ marginTop: -8 }}>
            A UI component crashed. Reload to recover.
          </p>
          <button type="button" className="cc-btn cc-btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

