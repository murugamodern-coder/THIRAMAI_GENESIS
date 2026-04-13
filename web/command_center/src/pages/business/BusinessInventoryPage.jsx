import { useCallback, useEffect, useState } from "react";

import {
  createInventoryItem,
  createInventorySupplier,
  fetchInventoryAlerts,
  fetchInventoryList,
  fetchInventorySuppliers,
  postInventoryStockMovement,
  updateInventoryItem,
} from "../../api/commandCenterApi.js";

export default function BusinessInventoryPage() {
  const [items, setItems] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({
    sku_name: "",
    location: "",
    quantity: "0",
    unit_price: "",
    unit_cost_pre_tax: "",
    gst_rate_percent: "",
    hsn_code: "",
    reorder_point: "",
    external_ref: "",
  });
  const [mov, setMov] = useState({ item_id: "", delta: "", notes: "" });
  const [sup, setSup] = useState({ name: "", phone: "", gstin: "" });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [list, al, supList] = await Promise.all([
        fetchInventoryList(),
        fetchInventoryAlerts().catch(() => ({ items: [] })),
        fetchInventorySuppliers().catch(() => ({ suppliers: [] })),
      ]);
      setItems(list?.items || []);
      setAlerts(al?.items || []);
      setSuppliers(supList?.suppliers || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
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
        unit_cost_pre_tax: form.unit_cost_pre_tax ? Number(form.unit_cost_pre_tax) : null,
        gst_rate_percent: form.gst_rate_percent ? Number(form.gst_rate_percent) : null,
        hsn_code: form.hsn_code.trim() || null,
        reorder_point: form.reorder_point ? Number(form.reorder_point) : null,
        external_ref: form.external_ref.trim() || null,
      });
      setForm({
        sku_name: "",
        location: "",
        quantity: "0",
        unit_price: "",
        unit_cost_pre_tax: "",
        gst_rate_percent: "",
        hsn_code: "",
        reorder_point: "",
        external_ref: "",
      });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Create failed");
    }
  }

  async function submitMovement(e) {
    e.preventDefault();
    setErr(null);
    try {
      await postInventoryStockMovement({
        inventory_item_id: Number(mov.item_id),
        quantity_delta: Number(mov.delta),
        movement_type: Number(mov.delta) >= 0 ? "IN" : "OUT",
        notes: mov.notes || null,
      });
      setMov({ item_id: "", delta: "", notes: "" });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Movement failed");
    }
  }

  async function addSupplier(e) {
    e.preventDefault();
    setErr(null);
    try {
      await createInventorySupplier({
        name: sup.name.trim(),
        phone: sup.phone.trim() || null,
        gstin: sup.gstin.trim() || null,
      });
      setSup({ name: "", phone: "", gstin: "" });
      const supList = await fetchInventorySuppliers();
      setSuppliers(supList?.suppliers || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Supplier failed");
    }
  }

  return (
    <div>
      <h1 className="biz-page-title">Inventory</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>Low stock</h2>
        {alerts.length === 0 ? (
          <p className="cc-muted">No alerts.</p>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
            {alerts.slice(0, 15).map((a, i) => (
              <li key={i}>
                {a.sku_name} — qty {a.quantity}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="cc-card">
        <h2>Stock in / out</h2>
        <form onSubmit={submitMovement} style={{ display: "grid", gap: 8 }}>
          <select
            className="cc-select"
            value={mov.item_id}
            onChange={(e) => setMov((m) => ({ ...m, item_id: e.target.value }))}
            required
          >
            <option value="">Select SKU row</option>
            {items.map((it) => (
              <option key={it.id} value={it.id}>
                {it.sku_name} @ {it.location || "default"} (qty {it.quantity})
              </option>
            ))}
          </select>
          <input
            className="cc-input"
            type="number"
            step="any"
            placeholder="Qty delta (+ in, − out)"
            value={mov.delta}
            onChange={(e) => setMov((m) => ({ ...m, delta: e.target.value }))}
            required
          />
          <input
            className="cc-input"
            placeholder="Notes"
            value={mov.notes}
            onChange={(e) => setMov((m) => ({ ...m, notes: e.target.value }))}
          />
          <button type="submit" className="cc-btn cc-btn-primary">
            Record movement
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Add item (HSN, cost, sell)</h2>
        <form onSubmit={addItem} style={{ display: "grid", gap: 8 }}>
          <input
            className="cc-input"
            placeholder="SKU / item name"
            value={form.sku_name}
            onChange={(e) => setForm((f) => ({ ...f, sku_name: e.target.value }))}
            required
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              className="cc-input"
              placeholder="Location / bin"
              value={form.location}
              onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
            />
            <input
              className="cc-input"
              placeholder="HSN"
              value={form.hsn_code}
              onChange={(e) => setForm((f) => ({ ...f, hsn_code: e.target.value }))}
            />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Opening qty"
              value={form.quantity}
              onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
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
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Cost (pre-tax)"
              value={form.unit_cost_pre_tax}
              onChange={(e) => setForm((f) => ({ ...f, unit_cost_pre_tax: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Selling price"
              value={form.unit_price}
              onChange={(e) => setForm((f) => ({ ...f, unit_price: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="GST %"
              value={form.gst_rate_percent}
              onChange={(e) => setForm((f) => ({ ...f, gst_rate_percent: e.target.value }))}
            />
          </div>
          <input
            className="cc-input"
            placeholder="Unit note (e.g. pcs, kg) → external ref"
            value={form.external_ref}
            onChange={(e) => setForm((f) => ({ ...f, external_ref: e.target.value }))}
          />
          <button type="submit" className="cc-btn cc-btn-primary">
            Save item
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Suppliers</h2>
        <form onSubmit={addSupplier} style={{ display: "grid", gap: 8, marginBottom: 12 }}>
          <input
            className="cc-input"
            placeholder="Supplier name"
            value={sup.name}
            onChange={(e) => setSup((s) => ({ ...s, name: e.target.value }))}
            required
          />
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="cc-input"
              placeholder="Phone"
              value={sup.phone}
              onChange={(e) => setSup((s) => ({ ...s, phone: e.target.value }))}
            />
            <input
              className="cc-input"
              placeholder="GSTIN"
              value={sup.gstin}
              onChange={(e) => setSup((s) => ({ ...s, gstin: e.target.value }))}
            />
          </div>
          <button type="submit" className="cc-btn cc-btn-secondary">
            Add supplier
          </button>
        </form>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
          {suppliers.slice(0, 20).map((s) => (
            <li key={s.id}>
              {s.name}
              {s.phone ? ` · ${s.phone}` : ""}
            </li>
          ))}
        </ul>
      </div>

      <div className="cc-card">
        <h2>On hand</h2>
        <div style={{ overflowX: "auto" }}>
          <table className="cc-table" style={{ width: "100%", fontSize: 13 }}>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Qty</th>
                <th>HSN</th>
                <th>Cost</th>
                <th>Price</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td>{it.sku_name}</td>
                  <td>
                    <input
                      className="cc-input"
                      style={{ width: 72, padding: "4px 6px" }}
                      defaultValue={it.quantity}
                      onBlur={async (e) => {
                        const v = Number(e.target.value);
                        if (Number.isNaN(v)) return;
                        try {
                          await updateInventoryItem(it.id, { quantity: v });
                          load();
                        } catch {
                          /* ignore */
                        }
                      }}
                    />
                  </td>
                  <td>{it.hsn_code || "—"}</td>
                  <td>{it.unit_cost_pre_tax ?? "—"}</td>
                  <td>{it.unit_price ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
