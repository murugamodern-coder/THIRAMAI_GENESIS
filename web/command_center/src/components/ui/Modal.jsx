import { useEffect } from "react";
import { createPortal } from "react-dom";

export default function Modal({ open, onClose, title, size = "md", children }) {
  useEffect(() => {
    if (!open) return undefined;
    function onEsc(e) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div className="ui-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`ui-modal ui-modal--${size}`}
        role="dialog"
        aria-modal="true"
        aria-label={title || "Dialog"}
        onClick={(e) => e.stopPropagation()}
      >
        {title ? <header className="ui-modal__header"><h3>{title}</h3></header> : null}
        <div className="ui-modal__body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
