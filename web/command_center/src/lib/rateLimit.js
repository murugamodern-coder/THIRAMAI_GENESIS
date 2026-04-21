/**
 * Lightweight client-side throttling — no spam clicks / repeated API triggers.
 */

/** Returns a function that invokes fn at most once per `waitMs` (leading edge). */
export function throttle(fn, waitMs) {
  let last = 0;
  let t = null;
  return function throttled(...args) {
    const now = Date.now();
    const remaining = waitMs - (now - last);
    if (remaining <= 0) {
      if (t) {
        clearTimeout(t);
        t = null;
      }
      last = now;
      return fn.apply(this, args);
    }
    if (!t) {
      t = setTimeout(() => {
        last = Date.now();
        t = null;
        fn.apply(this, args);
      }, remaining);
    }
  };
}

/** Async: only one in-flight call per window; returns previous promise if still pending */
export function createAsyncThrottle(fn, waitMs) {
  let last = 0;
  let pending = null;
  return async function throttledAsync(...args) {
    const now = Date.now();
    if (now - last < waitMs && pending) {
      return pending;
    }
    last = now;
    pending = Promise.resolve()
      .then(() => fn.apply(this, args))
      .finally(() => {
        pending = null;
      });
    return pending;
  };
}
