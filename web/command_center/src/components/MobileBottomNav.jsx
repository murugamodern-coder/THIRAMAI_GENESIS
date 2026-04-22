import { NavLink } from "react-router-dom";

/**
 * Touch-first bottom navigation (mobile). Hidden from md breakpoint up.
 */
export default function MobileBottomNav() {
  return (
    <nav className="cc-mobile-nav" aria-label="Main">
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/dashboard">
        <span className="cc-mobile-nav__icon" aria-hidden>
          🧠
        </span>
        Brain
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/personal">
        <span className="cc-mobile-nav__icon" aria-hidden>
          👤
        </span>
        Personal
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/os/stock">
        <span className="cc-mobile-nav__icon" aria-hidden>
          📈
        </span>
        Stock
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/os/research">
        <span className="cc-mobile-nav__icon" aria-hidden>
          🔬
        </span>
        Research
      </NavLink>
      <NavLink className={({ isActive }) => `cc-mobile-nav__item${isActive ? " is-active" : ""}`} end to="/os/agentic-platform">
        <span className="cc-mobile-nav__icon" aria-hidden>
          ⚡
        </span>
        Agentic
      </NavLink>
    </nav>
  );
}
