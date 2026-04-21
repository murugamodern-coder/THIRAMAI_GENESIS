export default function Card({
  title,
  subtitle,
  icon,
  actions,
  footer,
  variant = "default",
  glass = false,
  children,
  className = "",
}) {
  return (
    <section className={`ui-card ui-card--${variant} ${glass ? "ui-card--glass" : ""} ${className}`.trim()}>
      {(title || subtitle || icon || actions) && (
        <header className="ui-card__header">
          <div className="ui-card__title-wrap">
            {icon ? <span className="ui-card__icon">{icon}</span> : null}
            <div>
              {title ? <h3 className="ui-card__title">{title}</h3> : null}
              {subtitle ? <p className="ui-card__subtitle">{subtitle}</p> : null}
            </div>
          </div>
          {actions ? <div className="ui-card__actions">{actions}</div> : null}
        </header>
      )}
      <div className="ui-card__body">{children}</div>
      {footer ? <footer className="ui-card__footer">{footer}</footer> : null}
    </section>
  );
}
