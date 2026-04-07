export default function LiveStatusPill({ status }) {
  const connected = status?.connected !== false;
  const paused = status?.paused === true;

  if (paused) {
    return <span className="cc-pill cc-pill--warning">Disconnected</span>;
  }
  if (!connected) {
    return <span className="cc-pill cc-pill--warning">Disconnected</span>;
  }
  return <span className="cc-pill cc-pill--success">Live</span>;
}

