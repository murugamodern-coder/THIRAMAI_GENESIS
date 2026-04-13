import { useCallback, useEffect, useState } from "react";

import { fetchBusinessExpenseList, postBusinessExpense } from "../../api/commandCenterApi.js";

const CATS = [
  { value: "raw_material", label: "Raw material" },
  { value: "labour_wages", label: "Labour / wages" },
  { value: "transport", label: "Transport" },
  { value: "electricity", label: "Electricity" },
  { value: "machine_maintenance", label: "Machine maintenance" },
  { value: "commission", label: "Commission / margin" },
  { value: "other", label: "Other" },
];

export default function BusinessExpensesPage() {
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({
    expense_date: new Date().toISOString().slice(0, 10),
    category: "raw_material",
    amount_inr: "",
    description: "",
  });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const out = await fetchBusinessExpenseList({ limit: 150 });
      setRows(out?.expenses || []);
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
      await postBusinessExpense({
        expense_date: form.expense_date,
        category: form.category,
        amount_inr: form.amount_inr,
        description: form.description || null,
      });
      setForm((f) => ({ ...f, amount_inr: "", description: "" }));
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Save failed");
    }
  }

  return (
    <div>
      <h1 className="biz-page-title">Expenses</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>Add expense</h2>
        <form onSubmit={submit} style={{ display: "grid", gap: 8 }}>
          <input
            className="cc-input"
            type="date"
            value={form.expense_date}
            onChange={(e) => setForm((f) => ({ ...f, expense_date: e.target.value }))}
          />
          <select
            className="cc-select"
            value={form.category}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
          >
            {CATS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          <input
            className="cc-input"
            type="number"
            step="any"
            placeholder="Amount ₹"
            value={form.amount_inr}
            onChange={(e) => setForm((f) => ({ ...f, amount_inr: e.target.value }))}
            required
          />
          <input
            className="cc-input"
            placeholder="Note"
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
          <button type="submit" className="cc-btn cc-btn-primary">
            Save
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Recent</h2>
        <ul style={{ margin: 0, paddingLeft: 16, fontSize: 14 }}>
          {rows.slice(0, 40).map((r) => (
            <li key={r.id} style={{ marginBottom: 6 }}>
              <strong>{r.expense_date}</strong> {r.category} — ₹{r.amount_inr}
              {r.description ? <span className="cc-muted"> — {r.description}</span> : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
