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
    <div
      className="relative flex min-h-screen overflow-hidden bg-[linear-gradient(to_bottom,#0f172a,#020617)]"
      style={{ color: "white" }}
    >
      <div
        className="pointer-events-none absolute left-1/2 top-1/3 z-0 h-96 w-96 -translate-x-1/2 rounded-full bg-cyan-500/5 blur-3xl"
        aria-hidden="true"
      />
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-slate-800 bg-slate-950/95 px-3 backdrop-blur md:hidden">
        <button
          type="button"
          onClick={() => setMobileNavOpen((v) => !v)}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium"
          style={{
            background: "rgba(255,255,255,0.1)",
            color: "#ffffff",
            border: "1px solid rgba(255,255,255,0.2)",
            borderRadius: "6px",
            padding: "6px 12px",
            cursor: "pointer",
          }}
          aria-label="Toggle menu"
        >
          Menu
        </button>
        <div className="text-xs font-semibold uppercase tracking-[0.2em]" style={{ color: "#ffffff" }}>
          Thiramai
        </div>
        <div className="h-8 w-8" aria-hidden="true" />
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
          <div className="text-xs font-semibold uppercase tracking-[0.2em]" style={{ color: "#ffffff" }}>
            Thiramai
          </div>
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            className="rounded-lg border border-slate-700 px-2 py-1 text-xs"
            style={{ color: "#ffffff" }}
          >
            Close
          </button>
        </div>
        <nav className="space-y-2">
          {visibleNav.map((item) => (
            <NavLink
              key={`m_${item.key}`}
              to={item.to}
              end={item.key !== "business" && item.key !== "personal"}
              onClick={() => setMobileNavOpen(false)}
              className={({ isActive }) =>
                `block rounded-lg px-4 py-3 text-base transition ${
                  isActive ? "bg-slate-800" : "hover:bg-slate-900"
                }`
              }
              style={{ color: "#ffffff" }}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-8 space-y-2">
          <button
            type="button"
            onClick={onSignOut}
            className="w-full rounded-lg border border-slate-800 px-4 py-3 text-sm transition hover:border-slate-700"
            style={{ color: "#ffffff" }}
          >
            Sign out
          </button>
        </div>
      </aside>

      <aside className="relative z-10 hidden w-56 shrink-0 border-r border-slate-900/80 bg-slate-950/80 p-5 backdrop-blur md:flex md:flex-col">
        <div className="mb-8 text-xs font-semibold uppercase tracking-[0.22em]" style={{ color: "#ffffff" }}>
          Thiramai
        </div>
        <nav className="space-y-1.5">
          {visibleNav.map((item) => (
            <NavLink
              key={item.key}
              to={item.to}
              end={item.key !== "business" && item.key !== "personal"}
              className={({ isActive }) =>
                `block rounded-xl px-3 py-2.5 text-sm transition ${
                  isActive
                    ? "bg-white shadow-[0_8px_24px_-18px_rgba(255,255,255,0.55)]"
                    : "hover:bg-slate-900/70"
                }`
              }
              style={({ isActive }) => ({ color: isActive ? "#0f172a" : "#ffffff" })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2">
          <button
            type="button"
            onClick={onSignOut}
            className="w-full rounded-xl border border-slate-900 px-3 py-2.5 text-sm transition hover:border-slate-700"
            style={{ color: "#ffffff" }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main id="cc-main-content" className="relative z-10 flex-1 overflow-y-auto px-2 pb-28 pt-3 sm:px-4 md:p-6">
        <div className="mx-auto w-full max-w-5xl">
          <section className="overflow-x-auto rounded-2xl bg-transparent p-3 sm:p-4">
            <Outlet />
          </section>
        </div>
      </main>
    </div>
  );
}
