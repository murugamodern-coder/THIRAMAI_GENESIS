import Button from "./Button.jsx";

const ILLUSTRATION = (
  <svg width="92" height="92" viewBox="0 0 92 92" fill="none" aria-hidden="true">
    <rect x="6" y="14" width="80" height="60" rx="12" fill="rgba(99,102,241,0.12)" />
    <circle cx="30" cy="42" r="8" fill="rgba(99,102,241,0.38)" />
    <rect x="44" y="36" width="28" height="4" rx="2" fill="rgba(99,102,241,0.48)" />
    <rect x="44" y="45" width="20" height="4" rx="2" fill="rgba(99,102,241,0.28)" />
  </svg>
);

export default function EmptyState({ title, description, actionLabel, onAction }) {
  return (
    <div className="ui-empty">
      {ILLUSTRATION}
      <h4>{title || "No data available"}</h4>
      <p className="cc-muted">{description || "Try changing filters or adding a new record."}</p>
      {actionLabel ? (
        <Button variant="secondary" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}
