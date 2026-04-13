import { useState } from "react";
import { Link } from "react-router-dom";

/**
 * Mobile-first quick actions (FAB). Hidden on desktop via CSS.
 */
export default function QuickActionsFAB() {
  const [open, setOpen] = useState(false);

  return (
    <div className="cc-fab-root">
      {open && (
        <div className="cc-fab-backdrop" aria-hidden onClick={() => setOpen(false)} />
      )}
      {open && (
        <div className="cc-fab-menu" role="menu">
          <Link role="menuitem" className="cc-fab-menu__item" to="/today" onClick={() => setOpen(false)}>
            Today brief
          </Link>
          <Link role="menuitem" className="cc-fab-menu__item" to="/personal/productivity" onClick={() => setOpen(false)}>
            Log task
          </Link>
          <Link role="menuitem" className="cc-fab-menu__item" to="/personal/finance" onClick={() => setOpen(false)}>
            Log expense
          </Link>
          <Link role="menuitem" className="cc-fab-menu__item" to="/personal/health" onClick={() => setOpen(false)}>
            Log health
          </Link>
          <Link role="menuitem" className="cc-fab-menu__item" to="/personal" onClick={() => setOpen(false)}>
            Schedule meeting
          </Link>
          <Link role="menuitem" className="cc-fab-menu__item" to="/ai" onClick={() => setOpen(false)}>
            Ask Jarvis
          </Link>
        </div>
      )}
      <button
        type="button"
        className={`cc-fab-main${open ? " is-open" : ""}`}
        aria-expanded={open}
        aria-label={open ? "Close quick actions" : "Open quick actions"}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "×" : "+"}
      </button>
    </div>
  );
}
