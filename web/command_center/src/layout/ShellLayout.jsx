import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { fetchAuthMe } from "../api/commandCenterApi.js";
import { ROLES } from "../lib/rbac.js";
import { useCommandStore } from "../store/useCommandStore.js";

const menuItems = [
  { key: "command", label: "Command", path: "/command-center", icon: "⚡", roles: [ROLES.OWNER, ROLES.STAFF] },
  { key: "control", label: "Control", path: "/os/control-center", icon: "🎛️", roles: [ROLES.OWNER] },
  { key: "business", label: "Business", path: "/business", icon: "💼", roles: [ROLES.OWNER, ROLES.STAFF] },
  { key: "personal", label: "Personal", path: "/today", icon: "👤", roles: [ROLES.OWNER, ROLES.STAFF, ROLES.FAMILY] },
];

const sidebarStyle = {
  position: "fixed",
  top: 0,
  left: 0,
  width: "240px",
  height: "100vh",
  background: "rgba(10, 15, 30, 0.98)",
  backdropFilter: "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
  borderRight: "1px solid rgba(255,255,255,0.06)",
  zIndex: 1000,
  display: "flex",
  flexDirection: "column",
  padding: "24px 16px",
};

const logoStyle = {
  fontSize: "18px",
  fontWeight: "700",
  color: "#ffffff",
  letterSpacing: "0.1em",
  marginBottom: "32px",
  paddingLeft: "12px",
};

const itemBaseStyle = {
  display: "flex",
  alignItems: "center",
  gap: "10px",
  padding: "10px 12px",
  borderRadius: "8px",
  color: "#94a3b8",
  textDecoration: "none",
  fontSize: "14px",
  fontWeight: "500",
  cursor: "pointer",
  transition: "all 0.15s ease",
  marginBottom: "4px",
};

const itemActiveStyle = {
  background: "rgba(59, 130, 246, 0.15)",
  color: "#ffffff",
  borderLeft: "2px solid #3b82f6",
};

const footerStyle = {
  marginTop: "auto",
  borderTop: "1px solid rgba(255,255,255,0.06)",
  paddingTop: "16px",
};

function itemsForRole(role) {
  if (role === ROLES.FAMILY) {
    return menuItems.filter((m) => m.key === "personal");
  }
  return menuItems.filter((m) => m.roles.includes(role));
}

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

  const visibleMenu = useMemo(() => itemsForRole(role), [role]);

  const onSignOut = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const emailPreview = useCommandStore((s) => s.me?.email) || "Account";

  const renderNav = (onNavigate) => (
    <>
      <div style={logoStyle}>THIRAMAI</div>
      <nav>
        {visibleMenu.map((item) => (
          <NavLink
            key={item.key}
            to={item.path}
            end={item.key !== "business" && item.key !== "personal"}
            onClick={onNavigate}
            style={({ isActive }) => ({
              ...itemBaseStyle,
              borderLeft: isActive ? "2px solid #3b82f6" : "2px solid transparent",
              ...(isActive ? itemActiveStyle : {}),
            })}
          >
            <span aria-hidden="true">{item.icon}</span>
            <span style={{ color: "inherit" }}>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div style={footerStyle}>
        <div
          style={{
            fontSize: "12px",
            color: "#94a3b8",
            paddingLeft: "12px",
            marginBottom: "12px",
            wordBreak: "break-all",
          }}
        >
          {String(emailPreview)}
        </div>
        <button
          type="button"
          onClick={onSignOut}
          style={{
            width: "100%",
            textAlign: "left",
            padding: "10px 12px",
            borderRadius: "8px",
            border: "1px solid rgba(255,255,255,0.08)",
            background: "transparent",
            color: "#ffffff",
            fontSize: "14px",
            cursor: "pointer",
          }}
        >
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <div
      className="relative flex min-h-screen overflow-hidden bg-[linear-gradient(to_bottom,#0f172a,#020617)]"
      style={{ color: "white" }}
    >
      <div
        className="pointer-events-none absolute left-1/2 top-1/3 z-0 h-96 w-96 -translate-x-1/2 rounded-full bg-cyan-500/5 blur-3xl"
        aria-hidden="true"
      />

      {/* Mobile: hamburger only (no duplicate header row) */}
      <button
        type="button"
        className="fixed left-3 top-3 z-[1001] flex h-11 w-11 items-center justify-center rounded-lg md:hidden"
        style={{
          background: "rgba(255,255,255,0.1)",
          color: "#ffffff",
          border: "1px solid rgba(255,255,255,0.2)",
          cursor: "pointer",
        }}
        aria-label="Open navigation menu"
        aria-expanded={mobileNavOpen}
        onClick={() => setMobileNavOpen((v) => !v)}
      >
        <span className="text-lg leading-none" aria-hidden="true">
          ☰
        </span>
      </button>

      {mobileNavOpen ? (
        <div
          className="fixed inset-0 z-[999] bg-black/50 md:hidden"
          onClick={() => setMobileNavOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setMobileNavOpen(false)}
          role="presentation"
          aria-hidden="true"
        />
      ) : null}

      {/* Single glass sidebar: off-canvas on small screens, always visible md+ */}
      <aside
        className={`fixed left-0 top-0 z-[1000] flex h-[100dvh] w-[240px] flex-col transition-transform duration-200 ease-out md:translate-x-0 ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{
          background: sidebarStyle.background,
          backdropFilter: sidebarStyle.backdropFilter,
          WebkitBackdropFilter: sidebarStyle.WebkitBackdropFilter,
          borderRight: sidebarStyle.borderRight,
          padding: sidebarStyle.padding,
        }}
      >
        <div className="mb-4 flex items-center justify-end md:hidden">
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            style={{ color: "#94a3b8", fontSize: "12px", background: "none", border: "none", cursor: "pointer" }}
          >
            Close
          </button>
        </div>
        {renderNav(() => setMobileNavOpen(false))}
      </aside>

      <main
        id="cc-main-content"
        className="relative z-10 flex-1 overflow-y-auto px-2 pb-28 pt-14 sm:px-4 md:ml-[240px] md:pt-6 md:p-6"
      >
        <div className="mx-auto w-full max-w-5xl">
          <section className="overflow-x-auto rounded-2xl bg-transparent p-3 sm:p-4">
            <Outlet />
          </section>
        </div>
      </main>
    </div>
  );
}
