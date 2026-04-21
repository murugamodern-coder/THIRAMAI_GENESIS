import { useEffect, useLayoutEffect } from "react";

/**
 * Enable with `VITE_CC_HOOK_DEBUG=1` (any build) or use dev server (import.meta.env.DEV).
 * Never gate hook *calls* on this flag — only logging inside hook bodies.
 */
export function ccHookDebugEnabled() {
  try {
    if (typeof import.meta !== "undefined" && import.meta.env?.DEV) return true;
    if (typeof import.meta !== "undefined" && import.meta.env?.VITE_CC_HOOK_DEBUG === "1") {
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

/** Synchronous, top of render body — not a React hook. */
export function logRenderStart(componentName, detail) {
  if (!ccHookDebugEnabled()) return;
  console.debug(`[cc:render:start] ${componentName}`, detail ?? "");
}

/**
 * After DOM updates — checkpoint for hook pipeline (mount + updates).
 * Always exactly one hook.
 */
export function useLayoutCommitTrace(componentName) {
  useLayoutEffect(() => {
    if (!ccHookDebugEnabled()) return;
    console.debug(`[cc:hook:layout-commit] ${componentName}`);
  });
}

/**
 * Runs after paint; dependency array omitted so this fires on every commit.
 * Always exactly one hook — safe for rules-of-hooks diagnostics.
 */
export function usePostCommitTrace(componentName) {
  useEffect(() => {
    if (!ccHookDebugEnabled()) return;
    console.debug(`[cc:hook:post-commit] ${componentName}`);
  });
}
