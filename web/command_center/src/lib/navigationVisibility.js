import { ROLES } from "./rbac.js";

export const NAV_ITEMS = [
  { key: "command", label: "Command", to: "/command-center", roles: [ROLES.OWNER, ROLES.STAFF] },
  { key: "control", label: "Control", to: "/control-center", roles: [ROLES.OWNER] },
  { key: "business", label: "Business", to: "/business", roles: [ROLES.OWNER, ROLES.STAFF] },
  { key: "personal", label: "Personal", to: "/personal", roles: [ROLES.OWNER, ROLES.FAMILY] },
];

export function visibleNavForRole(role) {
  if (role === ROLES.FAMILY) {
    return [{ key: "personal", label: "Personal", to: "/personal" }];
  }
  return NAV_ITEMS.filter((n) => n.roles.includes(role)).map((n) => ({
    ...n,
    to: role === ROLES.FAMILY && n.toFamily ? n.toFamily : n.to,
  }));
}
