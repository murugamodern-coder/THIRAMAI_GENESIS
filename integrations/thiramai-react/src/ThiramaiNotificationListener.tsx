"use client";

import * as React from "react";
import { thiramaiFetchJson, ThiramaiHttpError } from "./client";
import { useThiramaiConfig } from "./context";
import type { MasterDashboardResponse, Stage4AlertItem } from "./types";

export type ThiramaiNotificationListenerProps = {
  /**
   * Poll interval for Stage 4 (PostgreSQL notifications from alert_system).
   * Uses GET /analytics/master-dashboard and reads `active_alerts.items`.
   */
  pollIntervalMs?: number;
  /** Called when new unread alerts appear after the initial seeding poll */
  onNewAlerts?: (alerts: Stage4AlertItem[]) => void;
  /** Request browser Notification permission and show one desktop notification per batch */
  enableBrowserNotifications?: boolean;
  /** If false, listener does nothing (e.g. unauthenticated shell) */
  enabled?: boolean;
};

function requestNotificationPermission(): Promise<NotificationPermission> {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return Promise.resolve("denied");
  }
  if (Notification.permission === "granted") {
    return Promise.resolve("granted");
  }
  if (Notification.permission === "denied") {
    return Promise.resolve("denied");
  }
  return Notification.requestPermission();
}

/**
 * Global listener for **Stage 4 Alert System** issues (low stock, overdue debt, etc.).
 *
 * Polls the Control Tower endpoint so you do not need a dedicated WebSocket yet.
 * Mount once inside {@link ThiramaiProvider} (e.g. in root layout next to your toast host).
 */
export function ThiramaiNotificationListener({
  pollIntervalMs = 60_000,
  onNewAlerts,
  enableBrowserNotifications = false,
  enabled = true,
}: ThiramaiNotificationListenerProps) {
  const cfg = useThiramaiConfig();
  const seededRef = React.useRef(false);
  const knownIdsRef = React.useRef<Set<number>>(new Set());
  const onNewAlertsRef = React.useRef(onNewAlerts);
  onNewAlertsRef.current = onNewAlerts;

  React.useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    const tick = async () => {
      try {
        const dash = await thiramaiFetchJson<MasterDashboardResponse>(
          cfg,
          "/analytics/master-dashboard",
          { method: "GET" }
        );
        if (cancelled) return;

        const items = dash.active_alerts?.items ?? [];
        if (!dash.active_alerts?.ok) {
          return;
        }

        if (!seededRef.current) {
          items.forEach((i) => knownIdsRef.current.add(i.id));
          seededRef.current = true;
          return;
        }

        const fresh = items.filter((i) => !knownIdsRef.current.has(i.id));
        if (fresh.length === 0) return;

        fresh.forEach((i) => knownIdsRef.current.add(i.id));
        onNewAlertsRef.current?.(fresh);

        if (enableBrowserNotifications && typeof window !== "undefined") {
          const perm = await requestNotificationPermission();
          if (perm === "granted") {
            for (const a of fresh) {
              try {
                new Notification(a.title, {
                  body: a.body.replace(/\*\*/g, "").slice(0, 240),
                  tag: `thiramai-${a.id}`,
                });
              } catch {
                /* ignore */
              }
            }
          }
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ThiramaiHttpError && (e.status === 401 || e.status === 403)) {
          return;
        }
        console.warn("[ThiramaiNotificationListener] poll failed", e);
      }
    };

    tick();
    const id = window.setInterval(tick, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [cfg, enabled, pollIntervalMs, enableBrowserNotifications]);

  return null;
}
