import { NavLink } from "react-router-dom";

import { useCommandStore } from "../store/useCommandStore.js";

/**
 * Touch-first bottom navigation (mobile). Hidden from md breakpoint up.
 */
export default function MobileBottomNav() {
  const orgs = useCommandStore((s) => s.orgs);
  const bizOrgId =
    orgs.find((o) => o.is_current)?.organization?.id ?? orgs[0]?.organization?.id ?? 1;

  return (
    <nav className="cc-mobile-nav" aria-label="Main">
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/today">
        <span className="cc-mobile-nav__icon" aria-hidden>
          ☀
        </span>
        Today
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/personal">
        <span className="cc-mobile-nav__icon" aria-hidden>
          ◉
        </span>
        Personal
      </NavLink>
      <NavLink
        className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`}
        end
        to={`/business/${bizOrgId}/dashboard`}
      >
        <span className="cc-mobile-nav__icon" aria-hidden>
          ◆
        </span>
        Shop OS
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/ai">
        <span className="cc-mobile-nav__icon" aria-hidden>
          ✦
        </span>
        AI
      </NavLink>
    </nav>
  );
}
