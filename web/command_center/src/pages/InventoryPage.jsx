import { useCallback, useEffect, useState } from "react";

import {
  createInventoryItem,
  fetchInventoryAlerts,
  fetchInventoryList,
  updateInventoryItem,
} from "../api/commandCenterApi.js";
import Button from "../components/ui/Button.jsx";
import Card from "../components/ui/Card.jsx";
import Input from "../components/ui/Input.jsx";
import Table from "../components/ui/Table.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";

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
  const [query, setQuery] = useState("");
  const [stockFilter, setStockFilter] = useState("all");

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

  const filteredItems = (items ?? []).filter((row) => {
    const byQuery = query.trim()
      ? String(row?.sku_name || "").toLowerCase().includes(query.trim().toLowerCase())
      : true;
    if (!byQuery) return false;
    if (stockFilter === "low") return Number(row?.quantity) <= Number(row?.reorder_point ?? 0);
    if (stockFilter === "healthy") return Number(row?.quantity) > Number(row?.reorder_point ?? 0);
    return true;
  });

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>Inventory</h1>
      {err && <p className="cc-error">{err}</p>}

      <Card title="Search and filters" subtitle="Use category/status filters and bulk actions">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Input variant="search" placeholder="Search SKU..." value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="cc-select" value={stockFilter} onChange={(e) => setStockFilter(e.target.value)}>
            <option value="all">All stock levels</option>
            <option value="low">Low stock</option>
            <option value="healthy">Healthy stock</option>
          </select>
          <Button variant="secondary" size="sm">Bulk export</Button>
          <Button variant="secondary" size="sm">Bulk update</Button>
        </div>
      </Card>

      <Card title="Low stock">
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
      </Card>

      <Card title="Add item">
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
          <Button type="submit" variant="primary" size="md">Add</Button>
        </form>
      </Card>

      <Card title="Stock table">
        <h2>Stock</h2>
        {filteredItems.length === 0 ? (
          <EmptyState title="No inventory items" description="Try adjusting filters or adding an item." />
        ) : (
          <Table
            rows={filteredItems}
            columns={[
              { key: "sku_name", label: "SKU" },
              { key: "location", label: "Location", render: (r) => r.location || "—" },
              { key: "quantity", label: "Qty" },
              { key: "reorder_point", label: "Reorder", render: (r) => r.reorder_point ?? "—" },
              {
                key: "actions",
                label: "Quick edit",
                render: (row) => (
                  <div style={{ display: "flex", gap: 6 }}>
                    <input
                      className="cc-input"
                      style={{ width: 100 }}
                      type="number"
                      step="any"
                      placeholder={String(row.quantity)}
                      value={editQty[row.id] ?? ""}
                      onChange={(e) => setEditQty((q) => ({ ...q, [row.id]: e.target.value }))}
                    />
                    <Button variant="secondary" size="sm" onClick={() => saveQty(row.id)}>Save</Button>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Card>
      <Button variant="primary" className="cc-fab-main" aria-label="Add inventory item">+</Button>
    </div>
  );
}
