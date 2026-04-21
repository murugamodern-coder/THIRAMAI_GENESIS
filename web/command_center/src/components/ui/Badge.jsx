export default function Badge({ children, variant = "neutral", size = "md", dot = false, className = "" }) {
  return (
    <span className={`ui-badge ui-badge--${variant} ui-badge--${size} ${className}`.trim()}>
      {dot ? <span className="ui-badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
