import { ROLES } from "./rbac.js";

export const NAV_ITEMS = [
  { key: "brain", label: "Brain", to: "/brain", roles: [ROLES.OWNER] },
  { key: "tasks", label: "Tasks", to: "/today", roles: [ROLES.OWNER], toFamily: "/personal" },
  { key: "automation", label: "Automation", to: "/automation", roles: [ROLES.OWNER] },
  { key: "integrations", label: "Integrations", to: "/integrations", roles: [ROLES.OWNER] },
  { key: "opportunities", label: "Opportunities", to: "/opportunities", roles: [ROLES.OWNER] },
  { key: "learning", label: "Learning", to: "/learning", roles: [ROLES.OWNER] },
  { key: "control", label: "Control Center", to: "/control-center", roles: [ROLES.OWNER] },
  { key: "money_loop", label: "Money Loop", to: "/money-loop", roles: [ROLES.OWNER] },
  { key: "command_center", label: "Command Center", to: "/war-room", roles: [ROLES.OWNER] },
  { key: "research_projects", label: "Research Projects", to: "/research-projects", roles: [ROLES.OWNER] },
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
