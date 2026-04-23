import { ROLES } from "./rbac.js";

export const NAV_ITEMS = [
  { key: "brain", label: "Brain", to: "/dashboard", roles: [ROLES.OWNER] },
  { key: "tasks", label: "Tasks", to: "/today", roles: [ROLES.OWNER], toFamily: "/personal" },
  { key: "business", label: "Business", to: "/dashboard/inventory", roles: [ROLES.OWNER, ROLES.STAFF] },
  { key: "money", label: "Money", to: "/os/stock", roles: [ROLES.OWNER] },
  { key: "research", label: "Research", to: "/os/research", roles: [ROLES.OWNER] },
  { key: "build", label: "Build", to: "/os/agentic-platform", roles: [ROLES.OWNER] },
];

export function visibleNavForRole(role) {
  if (role === ROLES.FAMILY) {
    return [{ key: "tasks", label: "Tasks", to: "/personal" }];
  }
  return NAV_ITEMS.filter((n) => n.roles.includes(role)).map((n) => ({
    ...n,
    to: role === ROLES.FAMILY && n.toFamily ? n.toFamily : n.to,
  }));
}
