import { useCallback, useEffect, useState } from "react";

import { fetchBusinessTasks, patchBusinessTask, postBusinessTask } from "../../api/commandCenterApi.js";

const PRESETS = {
  machine_startup: [
    { label: "Safety guards OK", done: false },
    { label: "Lubrication checked", done: false },
    { label: "Trial run 5 min", done: false },
  ],
  daily_open: [
    { label: "Lights & power", done: false },
    { label: "Open cash / float", done: false },
    { label: "Signage out", done: false },
  ],
  daily_close: [
    { label: "Cash counted", done: false },
    { label: "Stock secured", done: false },
    { label: "Alarms set", done: false },
  ],
};

export default function BusinessTasksPage() {
  const [tasks, setTasks] = useState([]);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({
    title: "",
    owner_name: "",
    due_at: "",
    task_type: "general",
  });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const out = await fetchBusinessTasks(120);
      setTasks(out?.tasks || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function submit(e) {
    e.preventDefault();
    setErr(null);
    try {
      const tt = form.task_type;
      const checklist = PRESETS[tt] ? JSON.parse(JSON.stringify(PRESETS[tt])) : [];
      await postBusinessTask({
        title: form.title.trim(),
        owner_name: form.owner_name.trim(),
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
        task_type: tt,
        checklist_json: checklist,
      });
      setForm({ title: "", owner_name: "", due_at: "", task_type: "general" });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Create failed");
    }
  }

  async function toggleCheck(task, idx) {
    const list = Array.isArray(task.checklist_json) ? [...task.checklist_json] : [];
    if (!list[idx]) return;
    list[idx] = { ...list[idx], done: !list[idx].done };
    try {
      await patchBusinessTask(task.id, { checklist_json: list });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Update failed");
    }
  }

  async function setStatus(task, status) {
    try {
      await patchBusinessTask(task.id, { status });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Update failed");
    }
  }

  return (
    <div>
      <h1 className="biz-page-title">Tasks</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>New task / checklist</h2>
        <form onSubmit={submit} style={{ display: "grid", gap: 8 }}>
          <input
            className="cc-input"
            placeholder="Title"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            required
          />
          <input
            className="cc-input"
            placeholder="Owner (name)"
            value={form.owner_name}
            onChange={(e) => setForm((f) => ({ ...f, owner_name: e.target.value }))}
          />
          <input
            className="cc-input"
            type="datetime-local"
            value={form.due_at}
            onChange={(e) => setForm((f) => ({ ...f, due_at: e.target.value }))}
          />
          <select
            className="cc-select"
            value={form.task_type}
            onChange={(e) => setForm((f) => ({ ...f, task_type: e.target.value }))}
          >
            <option value="general">General</option>
            <option value="machine_startup">Machine startup</option>
            <option value="daily_open">Daily opening</option>
            <option value="daily_close">Daily closing</option>
          </select>
          <button type="submit" className="cc-btn cc-btn-primary">
            Add
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Pending</h2>
        {tasks.filter((t) => t.status === "pending").length === 0 ? (
          <p className="cc-muted">No pending tasks.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {tasks
              .filter((t) => t.status === "pending")
              .map((t) => (
                <li key={t.id} className="cc-card" style={{ marginBottom: 10, padding: 12 }}>
                  <div style={{ fontWeight: 600 }}>{t.title}</div>
                  <div className="cc-muted" style={{ fontSize: 12 }}>
                    {t.task_type} · {t.owner_name || "Unassigned"}
                    {t.due_at ? ` · due ${t.due_at}` : ""}
                  </div>
                  {Array.isArray(t.checklist_json) && t.checklist_json.length > 0 && (
                    <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                      {t.checklist_json.map((c, i) => (
                        <li key={i} style={{ marginBottom: 4 }}>
                          <label style={{ cursor: "pointer" }}>
                            <input
                              type="checkbox"
                              checked={!!c.done}
                              onChange={() => toggleCheck(t, i)}
                            />{" "}
                            {c.label || `Step ${i + 1}`}
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                    <button type="button" className="cc-btn cc-btn-secondary" onClick={() => setStatus(t, "done")}>
                      Mark done
                    </button>
                    <button
                      type="button"
                      className="cc-btn cc-btn-secondary"
                      onClick={() => setStatus(t, "cancelled")}
                    >
                      Cancel
                    </button>
                  </div>
                </li>
              ))}
          </ul>
        )}
      </div>

      <div className="cc-card">
        <h2>Staff attendance</h2>
        <p className="cc-muted" style={{ fontSize: 13 }}>
          Check-in/out uses staff profiles: POST <code>/business/attendance/check-in</code> with{" "}
          <code>staff_profile_id</code> from Command Center HR setup. This mobile view focuses on operational
          tasks; wire handheld attendance in a follow-up if you want one-tap buttons here.
        </p>
      </div>
    </div>
  );
}
