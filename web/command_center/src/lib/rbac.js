export const ROLES = Object.freeze({
  OWNER: "OWNER",
  STAFF: "STAFF",
  FAMILY: "FAMILY",
});

export const PERMISSIONS = Object.freeze({
  APPROVE: "APPROVE",
  EXECUTE: "EXECUTE",
  OVERRIDE_AI: "OVERRIDE_AI",
  VIEW: "VIEW",
});

export function inferRole(me) {
  const raw = (
    me?.role?.name ||
    me?.role ||
    me?.user_role ||
    (Array.isArray(me?.roles) ? me.roles[0]?.name || me.roles[0] : null) ||
    (me?.is_admin ? "owner" : null) ||
    ""
  );
  const v = String(raw || "").toUpperCase();
  if (v.includes("OWNER") || v.includes("ADMIN") || v.includes("MANAGER")) return ROLES.OWNER;
  if (v.includes("STAFF") || v.includes("OPERATOR") || v.includes("WORKER")) return ROLES.STAFF;
  if (v.includes("FAMILY")) return ROLES.FAMILY;
  return ROLES.FAMILY;
}

export function can(roleOrMe, permission) {
  const role = typeof roleOrMe === "string" ? roleOrMe : inferRole(roleOrMe);
  switch (permission) {
    case PERMISSIONS.VIEW:
      return true;
    case PERMISSIONS.EXECUTE:
      return role === ROLES.OWNER || role === ROLES.STAFF;
    case PERMISSIONS.APPROVE:
    case PERMISSIONS.OVERRIDE_AI:
      return role === ROLES.OWNER;
    default:
      return false;
  }
}

export function defaultRouteForRole(role) {
  if (role === ROLES.STAFF) return "/command-center";
  if (role === ROLES.FAMILY) return "/personal";
  return "/command-center";
}

