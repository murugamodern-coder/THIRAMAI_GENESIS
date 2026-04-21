import { NavLink } from "react-router-dom";

/**
 * Touch-first bottom navigation (mobile). Hidden from md breakpoint up.
 */
export default function MobileBottomNav() {
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
        to="/dashboard/inventory"
      >
        <span className="cc-mobile-nav__icon" aria-hidden>
          ◆
        </span>
        Business
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/os/stock">
        <span className="cc-mobile-nav__icon" aria-hidden>
          ◍
        </span>
        Stock
      </NavLink>
    </nav>
  );
}
