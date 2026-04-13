import { NavLink } from "react-router-dom";

/**
 * Touch-first bottom navigation (mobile). Hidden from md breakpoint up.
 */
export default function MobileBottomNav() {
  return (
    <nav className="cc-mobile-nav" aria-label="Main">
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/today">
        Today
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/personal">
        Personal
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/dashboard">
        Business
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/ai">
        AI
      </NavLink>
    </nav>
  );
}
