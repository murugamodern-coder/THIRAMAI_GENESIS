import { useMemo, useState } from "react";

import { queryAudit } from "../../lib/auditLogger.js";

export default function AuditPanel() {
  const [q, setQ] = useState("");
  const [actionType, setActionType] = useState("");

  const rows = useMemo(() => queryAudit({ q, actionType: actionType || undefined, limit: 80 }), [q, actionType]);
  const actions = useMemo(() => {
    const set = new Set(rows.map((r) => r.actionType));
    return Array.from(set).sort();
  }, [rows]);

  return (
    <div className="cc-card">
      <h2>Audit log</h2>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
        <input
          className="cc-input"
          style={{ maxWidth: 260 }}
          placeholder="Search actions…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="cc-select" style={{ maxWidth: 260 }} value={actionType} onChange={(e) => setActionType(e.target.value)}>
          <option value="">All actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <span className="cc-muted" style={{ fontSize: 12 }}>
          Local-first (mirrored to usage logs when available)
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="cc-muted" style={{ margin: 0 }}>
          No audit events yet.
        </p>
      ) : (
        <div className="cc-table-wrap">
          <table className="cc-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>User</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Result</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{String(r.timestamp).replace("T", " ").slice(0, 19)}</td>
                  <td>{r.userId ?? "—"}</td>
                  <td>{r.actionType}</td>
                  <td>
                    {r.entity}
                    {r.entityId != null ? `#${r.entityId}` : ""}
                  </td>
                  <td>
                    <span className={r.result === "FAIL" ? "cc-pill cc-pill--danger" : "cc-pill cc-pill--success"}>
                      {r.result}
                    </span>
                  </td>
                  <td>{r.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

