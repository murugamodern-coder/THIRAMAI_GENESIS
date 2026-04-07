export const ROLES = Object.freeze({
  ADMIN: "ADMIN",
  OPERATOR: "OPERATOR",
  VIEWER: "VIEWER",
});

export const PERMISSIONS = Object.freeze({
  APPROVE: "APPROVE",
  EXECUTE: "EXECUTE",
  OVERRIDE_AI: "OVERRIDE_AI",
  VIEW: "VIEW",
});

export function inferRole(me) {
  const raw =
    me?.role ||
    me?.user_role ||
    (Array.isArray(me?.roles) ? me.roles[0] : null) ||
    (me?.is_admin ? "ADMIN" : null) ||
    null;
  const v = String(raw || "").toUpperCase();
  if (v.includes("ADMIN") || v === "OWNER" || v === "MANAGER") return ROLES.ADMIN;
  if (v.includes("OPERATOR") || v.includes("STAFF")) return ROLES.OPERATOR;
  if (v.includes("VIEW")) return ROLES.VIEWER;
  return ROLES.VIEWER;
}

export function can(roleOrMe, permission) {
  const role = typeof roleOrMe === "string" ? roleOrMe : inferRole(roleOrMe);
  switch (permission) {
    case PERMISSIONS.VIEW:
      return true;
    case PERMISSIONS.EXECUTE:
      return role === ROLES.ADMIN || role === ROLES.OPERATOR;
    case PERMISSIONS.APPROVE:
    case PERMISSIONS.OVERRIDE_AI:
      return role === ROLES.ADMIN;
    default:
      return false;
  }
}

