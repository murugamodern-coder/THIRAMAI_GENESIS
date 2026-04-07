import { useToastStore } from "../store/useToastStore.js";

/**
 * Global API:
 *
 * showToast({ type, message, actionLabel?, onAction?, ttlMs? })
 */
export function showToast(input) {
  return useToastStore.getState().show(input);
}

