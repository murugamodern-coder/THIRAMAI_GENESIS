import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_INTERVAL_MS = 10_000;
const PAUSE_AFTER_CONSECUTIVE_FAILURES = 3;

function isPlainObject(x) {
  return x != null && typeof x === "object" && (x.constructor === Object || Object.getPrototypeOf(x) === Object.prototype);
}

function shallowEqual(a, b) {
  if (Object.is(a, b)) return true;
  if (!isPlainObject(a) || !isPlainObject(b)) return false;
  const ak = Object.keys(a);
  const bk = Object.keys(b);
  if (ak.length !== bk.length) return false;
  for (const k of ak) {
    if (!Object.prototype.hasOwnProperty.call(b, k)) return false;
    if (!Object.is(a[k], b[k])) return false;
  }
  return true;
}

function defaultIsEqual(prev, next) {
  if (Object.is(prev, next)) return true;
  if (shallowEqual(prev, next)) return true;
  try {
    return JSON.stringify(prev) === JSON.stringify(next);
  } catch {
    return false;
  }
}

export function useLiveData(fetchFn, intervalMs = DEFAULT_INTERVAL_MS, options = {}) {
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;
  const isEqualRef = useRef(options?.isEqual || defaultIsEqual);
  isEqualRef.current = options?.isEqual || defaultIsEqual;

  const timerRef = useRef(null);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const hasDataRef = useRef(false);
  const lastDataRef = useRef(null);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true); // initial only
  const [error, setError] = useState(null);

  const [connected, setConnected] = useState(true);
  const [paused, setPaused] = useState(false);
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  const stop = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const runOnce = useCallback(async () => {
    if (paused) return null;
    if (inFlightRef.current) return null;
    inFlightRef.current = true;

    // avoid flicker: only show loading on very first run when there's no data yet
    if (!hasDataRef.current) setLoading(true);

    try {
      const next = await fetchFnRef.current();
      if (!mountedRef.current) return null;
      setError(null);
      setConnected(true);
      setConsecutiveFailures(0);
      hasDataRef.current = true;
      const prev = lastDataRef.current;
      const equal = prev != null && isEqualRef.current(prev, next) === true;
      if (!equal) {
        lastDataRef.current = next;
        setData(next);
      }
      setLastUpdatedAt(Date.now());
      return next;
    } catch (e) {
      if (!mountedRef.current) return null;
      setError(e);
      setConnected(false);
      setConsecutiveFailures((n) => n + 1);
      return null;
    } finally {
      if (mountedRef.current) setLoading(false);
      inFlightRef.current = false;
    }
  }, [paused]);

  const refresh = useCallback(async () => {
    setPaused(false);
    setConsecutiveFailures(0);
    return await runOnce();
  }, [runOnce]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stop();
    };
  }, [stop]);

  // Pause on repeated failures.
  useEffect(() => {
    if (paused) return;
    if (consecutiveFailures >= PAUSE_AFTER_CONSECUTIVE_FAILURES) {
      setPaused(true);
      stop();
    }
  }, [consecutiveFailures, paused, stop]);

  // Visibility-aware polling: stop when hidden, resume when visible.
  useEffect(() => {
    function onVis() {
      if (document.visibilityState === "hidden") {
        stop();
        return;
      }
      // Visible again: run immediately (once), then resume interval if not paused.
      runOnce();
      if (!paused && !timerRef.current) {
        timerRef.current = window.setInterval(() => {
          if (document.visibilityState !== "visible") return;
          runOnce();
        }, intervalMs);
      }
    }

    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [intervalMs, paused, runOnce, stop]);

  // Start polling on mount.
  useEffect(() => {
    runOnce();
    if (!paused && !timerRef.current) {
      timerRef.current = window.setInterval(() => {
        if (document.visibilityState !== "visible") return;
        runOnce();
      }, intervalMs);
    }
    return () => stop();
  }, [intervalMs, paused, runOnce, stop]);

  const status = useMemo(
    () => ({
      connected,
      paused,
      consecutiveFailures,
      lastUpdatedAt,
      intervalMs,
    }),
    [connected, paused, consecutiveFailures, lastUpdatedAt, intervalMs],
  );

  return { data, loading, error, refresh, status };
}

