import { NavLink } from "react-router-dom";

/**
 * Touch-first bottom navigation (mobile). Hidden from md breakpoint up.
 */
export default function MobileBottomNav() {
  return (
    <nav className="cc-mobile-nav" aria-label="Main">
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/command-center">
        Command
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/control-center">
        Control
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} to="/business">
        Business
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} to="/personal">
        Personal
      </NavLink>
    </nav>
  );
}
