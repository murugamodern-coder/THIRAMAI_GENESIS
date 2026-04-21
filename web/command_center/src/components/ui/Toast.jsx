function iconFor(type) {
  if (type === "success") return "✓";
  if (type === "error") return "!";
  if (type === "warning") return "!";
  return "i";
}

export default function Toast({ toast, onDismiss }) {
  const ttl = Number(toast?.ttlMs) > 0 ? Number(toast.ttlMs) : 4000;
  return (
    <div
      className={["cc-toast", `cc-toast--${toast?.type || "info"}`, toast?.leaving ? "cc-toast--leaving" : ""].filter(Boolean).join(" ")}
      role={toast?.type === "error" ? "alert" : "status"}
      aria-live={toast?.type === "error" ? "assertive" : "polite"}
    >
      <div className="cc-toast__icon" aria-hidden="true">
        {iconFor(toast?.type)}
      </div>
      <div className="cc-toast__body">
        <div className="cc-toast__message">{toast?.message}</div>
        {toast?.actionLabel && typeof toast?.onAction === "function" ? (
          <button type="button" className="cc-btn cc-btn-ghost cc-toast__action" onClick={toast.onAction}>
            {toast.actionLabel}
          </button>
        ) : null}
        <div className="ui-toast-progress" style={{ animationDuration: `${ttl}ms` }} />
      </div>
      <button type="button" className="cc-toast__close" aria-label="Close notification" onClick={() => onDismiss?.(toast?.id)}>
        ×
      </button>
    </div>
  );
}
