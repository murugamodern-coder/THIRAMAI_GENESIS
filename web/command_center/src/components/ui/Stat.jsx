import { useEffect, useState } from "react";
import Badge from "./Badge.jsx";

export default function Stat({ value = 0, label, trend = null, icon = null, sparkline = null }) {
  const [displayValue, setDisplayValue] = useState(0);
  const target = Number(value) || 0;

  useEffect(() => {
    let raf = null;
    const start = performance.now();
    const duration = 600;
    function animate(ts) {
      const p = Math.min(1, (ts - start) / duration);
      setDisplayValue(Math.round(target * p));
      if (p < 1) raf = requestAnimationFrame(animate);
    }
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  const trendVariant = trend == null ? "neutral" : trend >= 0 ? "success" : "error";

  return (
    <div className="ui-stat">
      <div className="ui-stat__head">
        <span className="ui-stat__label">{label}</span>
        {icon ? <span>{icon}</span> : null}
      </div>
      <div className="ui-stat__value">{displayValue.toLocaleString("en-IN")}</div>
      <div className="ui-stat__foot">
        {trend != null ? <Badge variant={trendVariant}>{trend >= 0 ? `+${trend}%` : `${trend}%`}</Badge> : null}
        {sparkline ? <span className="cc-muted">{sparkline}</span> : null}
      </div>
    </div>
  );
}
