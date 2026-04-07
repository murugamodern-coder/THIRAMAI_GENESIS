import { showToastDedup } from "./toastDedup.js";

function bestErrorMessage(err) {
  const d = err?.response?.data?.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (typeof err?.message === "string" && err.message.trim()) return err.message;
  return "Request failed";
}

/**
 * safeAsync(fn, options?)
 *
 * Wrap async calls so they never throw into React event handlers.
 * Optionally emits a deduped error toast with Retry.
 */
export function safeAsync(fn, options = {}) {
  return async (...args) => {
    try {
      return await fn(...args);
    } catch (err) {
      if (options.toast !== false) {
        showToastDedup({
          type: "error",
          message: options.errorMessage || bestErrorMessage(err),
          actionLabel: options.retryLabel,
          onAction:
            typeof options.onRetry === "function"
              ? () => options.onRetry(...args)
              : options.retry === true
                ? () => fn(...args)
                : undefined,
        });
      }
      if (typeof options.onError === "function") {
        try {
          options.onError(err);
        } catch {
          /* ignore */
        }
      }
      return null;
    }
  };
}

