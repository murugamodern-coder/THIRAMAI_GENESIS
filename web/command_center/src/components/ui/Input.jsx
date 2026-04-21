export default function Input({
  label,
  helperText,
  error,
  icon,
  variant = "default",
  className = "",
  id,
  ...props
}) {
  const uid = id || `ui-input-${Math.random().toString(36).slice(2, 8)}`;
  return (
    <div className={`ui-input-wrap ${className}`.trim()}>
      {label ? (
        <label className="ui-input-label" htmlFor={uid}>
          {label}
        </label>
      ) : null}
      <div className={`ui-input-field ui-input-field--${variant} ${error ? "is-error" : ""}`}>
        {icon ? <span className="ui-input-icon">{icon}</span> : null}
        <input id={uid} className="ui-input" {...props} aria-invalid={!!error} />
      </div>
      {error ? <p className="ui-input-error">{error}</p> : helperText ? <p className="ui-input-helper">{helperText}</p> : null}
    </div>
  );
}
