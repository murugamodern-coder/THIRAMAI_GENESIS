import { Component } from 'react';

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 32, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 500,
                        color: 'var(--color-text-primary)', marginBottom: 8 }}>
            Something went wrong
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)',
                        marginBottom: 16 }}>
            {this.state.error?.message || 'Unexpected error'}
          </div>
          <button onClick={() => this.setState({ hasError: false, error: null })}
            style={{ fontSize: 12, padding: '6px 16px', borderRadius: 8,
                     border: '0.5px solid var(--color-border-secondary)',
                     background: 'transparent', cursor: 'pointer',
                     color: 'var(--color-text-primary)', fontFamily: 'inherit' }}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
