import { memo } from "react";

function LoadingSkeleton({ compact = false }) {
  const h = compact ? 100 : 200;
  return (
    <div className="cc-skeleton-root" aria-busy="true" aria-label="Loading charts">
      {!compact ? <div className="cc-skeleton cc-skeleton--wide" /> : null}
      <div className="cc-skeleton-grid">
        <div className="cc-skeleton cc-skeleton--chart" style={{ height: h }} />
        <div className="cc-skeleton cc-skeleton--chart" style={{ height: h }} />
      </div>
    </div>
  );
}

export default memo(LoadingSkeleton);
