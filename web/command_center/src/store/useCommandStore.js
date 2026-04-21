import { create } from "zustand";
import { setToken, TOKEN_KEY } from "../api/client.js";
import { inferRole } from "../lib/rbac.js";

export const useCommandStore = create((set) => ({
  token: typeof localStorage !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null,
  me: null,
  role: "VIEWER",
  orgs: [],
  setToken: (t) => {
    setToken(t);
    set({ token: t });
  },
  logout: () => {
    setToken(null);
    set({ token: null, me: null, role: "VIEWER", orgs: [] });
  },
  setMe: (me) => set({ me, role: inferRole(me) }),
  setOrgs: (orgs) => set({ orgs }),
}));

export function getCurrentRole() {
  try {
    return useCommandStore.getState().role || "VIEWER";
  } catch {
    return "VIEWER";
  }
}
