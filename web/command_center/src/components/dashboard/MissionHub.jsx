import { useState } from "react";

import { resolveDecision } from "../../api/commandCenterApi.js";
import { publish } from "../../lib/eventBus.js";
import { can, PERMISSIONS } from "../../lib/rbac.js";
import { useCommandStore } from "../../store/useCommandStore.js";
import { safeAsync } from "../../lib/safeAsync.js";
import { showToastDedup } from "../../lib/toastDedup.js";

export default function MissionHub({ items, onResolved }) {
  const [busyId, setBusyId] = useState(null);
  const [err, setErr] = useState(null);
  const role = useCommandStore((s) => s.role);
  const canApprove = can(role, PERMISSIONS.APPROVE);

  async function act(id, status) {
    setErr(null);
    setBusyId(id);
    const run = safeAsync(
      async () => {
        await resolveDecision(id, status);
        if (status === "approved") {
          showToastDedup({ type: "success", message: "Mission approved" });
        } else if (status === "rejected") {
          showToastDedup({ type: "warning", message: "Mission rejected" });
        } else {
          showToastDedup({ type: "success", message: "Mission updated" });
        }
        publish("mission:updated", { id, status });
        publish("dashboard:refresh", { source: "mission:updated" });
        onResolved?.();
      },
      {
        errorMessage: status === "approved" ? "Failed to approve mission" : "Failed to reject mission",
        retry: true,
        onError: (e) => {
          const d = e?.response?.data?.detail;
          const msg = typeof d === "string" ? d : e?.message || "Action failed";
          setErr(msg);
        },
      },
    );
    try {
      await run();
    } finally {
      setBusyId(null);
    }
  }

  if (!items?.length) {
    return (
      <div className="cc-card">
        <h2>Mission hub — AI decisions</h2>
        <p className="cc-muted" style={{ margin: 0 }}>
          No pending approvals. When the AI triggers a high-impact action, it will appear here for review.
        </p>
      </div>
    );
  }

  return (
    <div className="cc-card">
      <h2>Mission hub — AI decisions</h2>
      {err && <p className="cc-error">{err}</p>}
      <div className="cc-table-wrap">
        <table className="cc-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Priority</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td>{row.action}</td>
                <td>{row.entity || "—"}</td>
                <td>
                  <span
                    className={
                      row.priority === "emergency" || row.priority === "urgent"
                        ? "cc-pill cc-pill--warning"
                        : "cc-pill cc-pill--neutral"
                    }
                  >
                    {row.priority ?? "—"}
                  </span>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button
                    type="button"
                    className="cc-btn cc-btn-primary"
                    disabled={!canApprove || busyId === row.id}
                    onClick={() => act(row.id, "approved")}
                  >
                    Approve
                  </button>{" "}
                  <button
                    type="button"
                    className="cc-btn cc-btn-danger"
                    disabled={!canApprove || busyId === row.id}
                    onClick={() => act(row.id, "rejected")}
                  >
                    Reject
                  </button>
                  {!canApprove && (
                    <span className="cc-muted" style={{ marginLeft: 8, fontSize: 12 }}>
                      Admin required
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
