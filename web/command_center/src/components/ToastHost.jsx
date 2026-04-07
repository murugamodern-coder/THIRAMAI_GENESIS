import { useToastStore } from "../store/useToastStore.js";

function iconFor(type) {
  switch (type) {
    case "success":
      return "✓";
    case "error":
      return "!";
    case "warning":
      return "!";
    default:
      return "i";
  }
}

export default function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="cc-toast-host" role="region" aria-label="Notifications">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={[
            "cc-toast",
            `cc-toast--${t.type || "info"}`,
            t.leaving ? "cc-toast--leaving" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          role={t.type === "error" ? "alert" : "status"}
          aria-live={t.type === "error" ? "assertive" : "polite"}
        >
          <div className="cc-toast__icon" aria-hidden="true">
            {iconFor(t.type)}
          </div>
          <div className="cc-toast__body">
            <div className="cc-toast__message">{t.message}</div>
            {t.actionLabel && typeof t.onAction === "function" && (
              <button
                type="button"
                className="cc-btn cc-btn-ghost cc-toast__action"
                onClick={() => {
                  try {
                    t.onAction();
                  } finally {
                    dismiss(t.id);
                  }
                }}
              >
                {t.actionLabel}
              </button>
            )}
          </div>
          <button
            type="button"
            className="cc-toast__close"
            aria-label="Close notification"
            onClick={() => dismiss(t.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

