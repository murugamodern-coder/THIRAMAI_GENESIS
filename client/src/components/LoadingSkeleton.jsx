export function LoadingSkeleton({ rows = 3, height = 40 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{
          height,
          borderRadius: 8,
          background: 'var(--color-background-secondary)',
          opacity: 1,
          animation: 'skeleton-pulse 1.5s ease-in-out infinite',
          animationDelay: `${i * 0.1}s`,
        }} />
      ))}
      <style>{`
        @keyframes skeleton-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

export function EmptyState({ icon = '○', title, subtitle, action }) {
  return (
    <div style={{ textAlign: 'center', padding: '32px 16px' }}>
      <div style={{ fontSize: 24, marginBottom: 8, opacity: 0.3 }}>{icon}</div>
      <div style={{ fontSize: 13, fontWeight: 500,
                    color: 'var(--color-text-primary)', marginBottom: 4 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 12,
                                  color: 'var(--color-text-secondary)' }}>{subtitle}</div>}
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  );
}
