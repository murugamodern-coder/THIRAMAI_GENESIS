import { useCallback, useEffect, useState } from "react";

import {
  createInventoryItem,
  fetchInventoryAlerts,
  fetchInventoryList,
  updateInventoryItem,
} from "../api/commandCenterApi.js";

export default function InventoryPage() {
  const [items, setItems] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({
    sku_name: "",
    location: "",
    quantity: "0",
    unit_price: "",
    reorder_point: "",
  });
  const [editQty, setEditQty] = useState({});

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [list, al] = await Promise.all([
        fetchInventoryList(),
        fetchInventoryAlerts().catch(() => ({ items: [] })),
      ]);
      setItems(list?.items || []);
      setAlerts(al?.items || []);
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : e?.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function addItem(e) {
    e.preventDefault();
    setErr(null);
    try {
      await createInventoryItem({
        sku_name: form.sku_name.trim(),
        location: form.location.trim(),
        quantity: Number(form.quantity) || 0,
        unit_price: form.unit_price ? Number(form.unit_price) : null,
        reorder_point: form.reorder_point ? Number(form.reorder_point) : null,
      });
      setForm({ sku_name: "", location: "", quantity: "0", unit_price: "", reorder_point: "" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : "Create failed");
    }
  }

  async function saveQty(id) {
    const raw = editQty[id];
    if (raw === undefined) return;
    setErr(null);
    try {
      await updateInventoryItem(id, { quantity: Number(raw) });
      setEditQty((prev) => {
        const n = { ...prev };
        delete n[id];
        return n;
      });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : "Update failed");
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>Inventory</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>Low stock</h2>
        {alerts.length === 0 ? (
          <p className="cc-muted">No low-stock SKUs for current threshold.</p>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {alerts.slice(0, 20).map((a, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                <strong>{a.sku_name}</strong> — qty {a.quantity} @ {a.location || "—"}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="cc-card">
        <h2>Add item</h2>
        <form onSubmit={addItem} style={{ display: "grid", gap: 10, maxWidth: 480 }}>
          <input
            className="cc-input"
            placeholder="SKU / name"
            value={form.sku_name}
            onChange={(e) => setForm((f) => ({ ...f, sku_name: e.target.value }))}
            required
          />
          <input
            className="cc-input"
            placeholder="Location"
            value={form.location}
            onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Quantity"
              value={form.quantity}
              onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Unit price (optional)"
              value={form.unit_price}
              onChange={(e) => setForm((f) => ({ ...f, unit_price: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Reorder point"
              value={form.reorder_point}
              onChange={(e) => setForm((f) => ({ ...f, reorder_point: e.target.value }))}
            />
          </div>
          <button type="submit" className="cc-btn cc-btn-primary" style={{ width: 120 }}>
            Add
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Stock</h2>
        <div className="cc-table-wrap">
          <table className="cc-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Location</th>
                <th>Qty</th>
                <th>Reorder</th>
                <th>Update qty</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id}>
                  <td>{row.sku_name}</td>
                  <td>{row.location || "—"}</td>
                  <td>{row.quantity}</td>
                  <td>{row.reorder_point ?? "—"}</td>
                  <td>
                    <input
                      className="cc-input"
                      style={{ width: 100 }}
                      type="number"
                      step="any"
                      placeholder={String(row.quantity)}
                      value={editQty[row.id] ?? ""}
                      onChange={(e) => setEditQty((q) => ({ ...q, [row.id]: e.target.value }))}
                    />{" "}
                    <button type="button" className="cc-btn" onClick={() => saveQty(row.id)}>
                      Save
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
