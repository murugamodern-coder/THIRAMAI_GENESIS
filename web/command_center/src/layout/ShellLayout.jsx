import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { fetchAuthMe } from "../api/commandCenterApi.js";
import { visibleNavForRole } from "../lib/navigationVisibility.js";
import { useCommandStore } from "../store/useCommandStore.js";

export default function ShellLayout() {
  const navigate = useNavigate();
  const token = useCommandStore((s) => s.token);
  const role = useCommandStore((s) => s.role);
  const setMe = useCommandStore((s) => s.setMe);
  const logout = useCommandStore((s) => s.logout);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (!token) return;
    fetchAuthMe()
      .then((profile) => {
        if (profile) setMe(profile);
      })
      .catch(() => {});
  }, [token, setMe]);

  const visibleNav = useMemo(() => {
    return visibleNavForRole(role);
  }, [role]);

  const onSignOut = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-slate-800 bg-slate-950/95 px-3 backdrop-blur md:hidden">
        <button
          type="button"
          onClick={() => setMobileNavOpen((v) => !v)}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-100"
          aria-label="Toggle menu"
        >
          Menu
        </button>
        <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Thiramai</div>
        <div className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300">{role}</div>
      </header>

      {mobileNavOpen ? (
        <div
          className="fixed inset-0 z-50 bg-slate-950/70 md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-72 transform border-r border-slate-800 bg-slate-950 p-4 transition-transform md:hidden ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="mb-6 flex items-center justify-between">
          <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Thiramai</div>
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200"
          >
            Close
          </button>
        </div>
        <nav className="space-y-2">
          {visibleNav.map((item) => (
            <NavLink
              key={`m_${item.key}`}
              to={item.to}
              end={item.key === "brain"}
              onClick={() => setMobileNavOpen(false)}
              className={({ isActive }) =>
                `block rounded-lg px-4 py-3 text-base transition ${
                  isActive
                    ? "bg-slate-800 text-white"
                    : "text-slate-300 hover:bg-slate-900 hover:text-white"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 space-y-2">
          <div className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-400">
            Role: <span className="font-medium text-slate-200">{role}</span>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            className="w-full rounded-lg border border-slate-700 px-4 py-3 text-sm text-slate-200"
          >
            Sign out
          </button>
        </div>
      </aside>

      <aside className="hidden w-64 shrink-0 border-r border-slate-800 bg-slate-950/90 p-4 md:flex md:flex-col">
        <div className="mb-6 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Thiramai</div>
        <nav className="space-y-1">
          {visibleNav.map((item) => (
            <NavLink
              key={item.key}
              to={item.to}
              end={item.key === "brain"}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-slate-800 text-white"
                    : "text-slate-300 hover:bg-slate-900 hover:text-white"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2">
          <div className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-400">
            Role: <span className="font-medium text-slate-200">{role}</span>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main id="cc-main-content" className="flex-1 overflow-y-auto px-2 pb-28 pt-3 sm:px-4 md:p-6">
        <div className="mx-auto w-full max-w-6xl">
          <section className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40 p-3 sm:p-4">
            <Outlet />
          </section>
        </div>
      </main>
    </div>
  );
}
