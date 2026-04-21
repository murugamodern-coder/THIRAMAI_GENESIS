export default function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  iconOnly = false,
  className = "",
  disabled = false,
  type = "button",
  ...props
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`ui-button ui-button--${variant} ui-button--${size} ${iconOnly ? "ui-button--icon-only" : ""} ${className}`.trim()}
      {...props}
    >
      {loading ? <span className="ui-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
