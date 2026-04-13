import { useEffect, useRef } from "react";

function localDayKey() {
  return new Date().toDateString();
}

/**
 * Browser Notification API — meeting (−30m), daily brief (~7:00 local), EMI (−3d).
 * Requires permission; schedules checks while the tab is open (not full Web Push).
 */
export function useSmartNotifications(brief, { enabled }) {
  const firedRef = useRef(new Set());

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || !("Notification" in window)) return;
    if (Notification.permission !== "granted") return;

    const tick = () => {
      const now = new Date();
      const day = localDayKey();

      // Daily brief ~7:00 local (once per calendar day)
      const h = now.getHours();
      const m = now.getMinutes();
      const briefKey = `brief7_${day}`;
      if (h === 7 && m < 15 && !firedRef.current.has(briefKey)) {
        firedRef.current.add(briefKey);
        const name = brief?.greeting?.display_name || "there";
        try {
          new Notification("THIRAMAI — Good morning", {
            body: `Your day is ready, ${name}. Open Today for your full brief.`,
            tag: briefKey,
          });
        } catch {
          /* ignore */
        }
      }

      if (!brief || typeof brief !== "object") return;

      // Meetings starting in ~30 minutes
      const meetings = brief.meetings_today || [];
      for (const mt of meetings) {
        if (!mt?.scheduled_at || !mt.id) continue;
        const t = new Date(mt.scheduled_at).getTime();
        if (Number.isNaN(t)) continue;
        const mins = Math.round((t - now.getTime()) / 60000);
        const key = `mt30_${mt.id}_${day}`;
        if (mins >= 25 && mins <= 35 && !firedRef.current.has(key)) {
          firedRef.current.add(key);
          try {
            new Notification("Meeting soon", {
              body: `${mt.title || "Meeting"} — starts in about ${mins} min.`,
              tag: key,
            });
          } catch {
            /* ignore */
          }
        }
      }

      // EMI due within 3 days
      const emi = brief.upcoming_emis;
      if (emi?.due) {
        const due = new Date(`${emi.due}T12:00:00`);
        if (!Number.isNaN(due.getTime())) {
          const sod = new Date(now);
          sod.setHours(0, 0, 0, 0);
          const days = Math.ceil((due.getTime() - sod.getTime()) / 86400000);
          const eid = emi.id ?? emi.name ?? "emi";
          const key = `emi3_${eid}_${day}`;
          if (days >= 0 && days <= 3 && !firedRef.current.has(key)) {
            firedRef.current.add(key);
            try {
              new Notification("EMI reminder", {
                body: `${emi.name || "Loan"} — due in ${days} day(s).`,
                tag: key,
              });
            } catch {
              /* ignore */
            }
          }
        }
      }
    };

    tick();
    const id = window.setInterval(tick, 60_000);
    return () => window.clearInterval(id);
  }, [brief, enabled]);
}

export async function requestNotificationPermission() {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return "unsupported";
  }
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  try {
    const p = await Notification.requestPermission();
    return p;
  } catch {
    return "denied";
  }
}
