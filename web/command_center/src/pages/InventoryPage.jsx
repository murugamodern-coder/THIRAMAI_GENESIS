import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createInventoryItem,
  deleteInventoryItem,
  fetchInventoryList,
  updateInventoryItem,
} from "../api/commandCenterApi.js";

const PAGE_SIZE = 20;
const EMPTY_FORM = {
  sku: "",
  name: "",
  category: "",
  stock: 0,
  min_stock: 0,
  price: "",
  description: "",
};

function toUiItem(row) {
  const stock = Number(row?.quantity ?? row?.stock ?? 0);
  const minStock = Number(row?.reorder_point ?? row?.min_stock ?? 0);
  const price = Number(row?.unit_price ?? row?.price ?? 0);
  return {
    id: row?.id,
    sku: String(row?.sku ?? row?.sku_name ?? ""),
    name: String(row?.name ?? row?.sku_name ?? "Untitled item"),
    category: String(row?.category ?? "General"),
    stock: Number.isFinite(stock) ? stock : 0,
    min_stock: Number.isFinite(minStock) ? minStock : 0,
    price: Number.isFinite(price) ? price : 0,
    description: String(row?.description ?? ""),
    raw: row,
  };
}

function stockStatus(item) {
  if (item.stock <= 0) return { label: "Out of Stock", className: "bg-red-500/15 text-red-300 border-red-500/30" };
  if (item.stock <= item.min_stock) return { label: "Low Stock", className: "bg-amber-500/15 text-amber-300 border-amber-500/30" };
  return { label: "In Stock", className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30" };
}

function StatCard({ label, value, danger = false }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${danger ? "text-red-300" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

function InventorySkeleton() {
  return Array.from({ length: 8 }).map((_, idx) => (
    <tr key={`sk_${idx}`} className="animate-pulse border-b border-slate-800">
      {Array.from({ length: 8 }).map((__, cIdx) => (
        <td key={`sk_${idx}_${cIdx}`} className="px-4 py-3">
          <div className="h-4 rounded bg-slate-800" />
        </td>
      ))}
    </tr>
  ));
}

export default function InventoryPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [categoryDraft, setCategoryDraft] = useState("all");
  const [stockDraft, setStockDraft] = useState("all");
  const [filters, setFilters] = useState({ search: "", category: "all", stock: "all" });
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const csvInputRef = useRef(null);

  const loadInventory = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchInventoryList();
      const rows = Array.isArray(data?.items) ? data.items : Array.isArray(data?.inventory) ? data.inventory : [];
      setItems(rows.map(toUiItem));
    } catch (e) {
      const d = e?.response?.data?.detail;
      setError(typeof d === "string" ? d : "Unable to load inventory");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInventory();
  }, [loadInventory]);

  const categories = useMemo(() => {
    const set = new Set(items.map((x) => x.category).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [items]);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      const q = filters.search.trim().toLowerCase();
      if (q) {
        const hay = `${item.sku} ${item.name}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (filters.category !== "all" && item.category !== filters.category) return false;
      if (filters.stock === "out" && item.stock !== 0) return false;
      if (filters.stock === "low" && !(item.stock > 0 && item.stock <= item.min_stock)) return false;
      if (filters.stock === "in" && !(item.stock > item.min_stock)) return false;
      return true;
    });
  }, [items, filters]);

  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, page]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  useEffect(() => {
    setPage(1);
  }, [filters]);

  const stats = useMemo(() => {
    const total = items.length;
    const low = items.filter((x) => x.stock > 0 && x.stock <= x.min_stock).length;
    const out = items.filter((x) => x.stock <= 0).length;
    const value = items.reduce((acc, x) => acc + x.stock * x.price, 0);
    return { total, low, out, value };
  }, [items]);

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  };

  const openEdit = (item) => {
    setEditingId(item.id);
    setForm({
      sku: item.sku,
      name: item.name,
      category: item.category,
      stock: item.stock,
      min_stock: item.min_stock,
      price: item.price,
      description: item.description,
    });
    setModalOpen(true);
  };

  const submitForm = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    const payload = {
      sku_name: String(form.sku || form.name || "").trim(),
      name: String(form.name || "").trim(),
      category: String(form.category || "General").trim(),
      quantity: Number(form.stock) || 0,
      reorder_point: Number(form.min_stock) || 0,
      unit_price: form.price === "" ? null : Number(form.price) || 0,
      description: String(form.description || "").trim(),
    };
    try {
      if (editingId) await updateInventoryItem(editingId, payload);
      else await createInventoryItem(payload);
      setModalOpen(false);
      await loadInventory();
    } catch (e2) {
      const d = e2?.response?.data?.detail;
      setError(typeof d === "string" ? d : "Unable to save item");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (item) => {
    if (!window.confirm(`Delete ${item.name}?`)) return;
    setError("");
    try {
      await deleteInventoryItem(item.id);
      await loadInventory();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setError(typeof d === "string" ? d : "Unable to delete item");
    }
  };

  const exportCsv = () => {
    const header = ["SKU", "Name", "Category", "Stock", "Min Stock", "Price"];
    const rows = filtered.map((x) => [x.sku, x.name, x.category, x.stock, x.min_stock, x.price]);
    const csv = [header, ...rows]
      .map((row) => row.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "inventory_export.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const onImportCsv = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setError("");
    try {
      const text = await file.text();
      const lines = text
        .split(/\r?\n/)
        .map((x) => x.trim())
        .filter(Boolean);
      if (lines.length < 2) throw new Error("CSV has no data rows");

      const header = lines[0].toLowerCase();
      const rows = lines.slice(1);
      const indexOf = (name) => header.split(",").findIndex((h) => h.trim().replace(/"/g, "") === name);
      const skuIdx = Math.max(0, indexOf("sku"));
      const nameIdx = indexOf("name");
      const catIdx = indexOf("category");
      const stockIdx = indexOf("stock");
      const minIdx = indexOf("min stock");
      const priceIdx = indexOf("price");

      for (const line of rows) {
        const cols = line.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
        const skuVal = cols[skuIdx] || cols[nameIdx] || "Imported SKU";
        await createInventoryItem({
          sku_name: skuVal,
          name: cols[nameIdx] || skuVal,
          category: cols[catIdx] || "General",
          quantity: Number(cols[stockIdx] || 0),
          reorder_point: Number(cols[minIdx] || 0),
          unit_price: cols[priceIdx] ? Number(cols[priceIdx]) : null,
        });
      }
      await loadInventory();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setError(typeof d === "string" ? d : e?.message || "Unable to import CSV");
    } finally {
      setImporting(false);
      if (csvInputRef.current) csvInputRef.current.value = "";
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-2xl font-semibold text-slate-100">📦 Inventory</h1>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={openCreate} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500">
            + Add Item
          </button>
          <button type="button" onClick={exportCsv} className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            📤 Bulk Export
          </button>
          <button type="button" onClick={() => setModalOpen(true)} className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            🔄 Bulk Update
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-3">
        <input
          className="min-w-[220px] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          placeholder="🔍 Search SKU/name..."
          value={searchDraft}
          onChange={(e) => setSearchDraft(e.target.value)}
        />
        <select
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          value={categoryDraft}
          onChange={(e) => setCategoryDraft(e.target.value)}
        >
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat === "all" ? "All Categories" : cat}
            </option>
          ))}
        </select>
        <select
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          value={stockDraft}
          onChange={(e) => setStockDraft(e.target.value)}
        >
          <option value="all">All Stock Levels</option>
          <option value="in">In Stock</option>
          <option value="low">Low Stock</option>
          <option value="out">Out of Stock</option>
        </select>
        <button
          type="button"
          onClick={() => setFilters({ search: searchDraft, category: categoryDraft, stock: stockDraft })}
          className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-900 hover:bg-white"
        >
          Apply filters
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Items" value={stats.total} />
        <StatCard label="Low Stock" value={stats.low} danger={stats.low > 0} />
        <StatCard label="Out of Stock" value={stats.out} danger={stats.out > 0} />
        <StatCard label="Total Value" value={`₹${stats.value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`} />
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          <div className="mb-2 font-medium">Unable to load inventory</div>
          <button type="button" onClick={loadInventory} className="rounded-lg bg-red-500 px-3 py-1.5 text-xs font-medium text-white">
            Retry
          </button>
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/50">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-900">
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
              {["SKU", "Name", "Category", "Stock", "Min Stock", "Price", "Status", "Actions"].map((h) => (
                <th key={h} className="px-4 py-3 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 text-slate-200">
            {loading ? (
              <InventorySkeleton />
            ) : paged.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-10">
                  <div className="mx-auto flex max-w-md flex-col items-center rounded-xl border border-slate-800 bg-slate-900/70 p-6 text-center">
                    <div className="mb-3 text-3xl">📦</div>
                    <h3 className="text-lg font-semibold text-slate-100">Start building your inventory</h3>
                    <p className="mt-2 text-sm text-slate-400">
                      Add your first item or import a CSV to quickly set up your stock catalog.
                    </p>
                    <div className="mt-5 flex flex-wrap justify-center gap-2">
                      <button
                        type="button"
                        onClick={openCreate}
                        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
                      >
                        Add Item
                      </button>
                      <button
                        type="button"
                        onClick={() => csvInputRef.current?.click()}
                        disabled={importing}
                        className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
                      >
                        {importing ? "Importing..." : "Import CSV"}
                      </button>
                    </div>
                    <input
                      ref={csvInputRef}
                      type="file"
                      accept=".csv,text/csv"
                      className="hidden"
                      onChange={onImportCsv}
                    />
                  </div>
                </td>
              </tr>
            ) : (
              paged.map((item) => {
                const status = stockStatus(item);
                return (
                  <tr key={item.id}>
                    <td className="px-4 py-3">{item.sku || "-"}</td>
                    <td className="px-4 py-3">{item.name}</td>
                    <td className="px-4 py-3">{item.category || "-"}</td>
                    <td className="px-4 py-3">{item.stock}</td>
                    <td className="px-4 py-3">{item.min_stock}</td>
                    <td className="px-4 py-3">₹{Number(item.price || 0).toLocaleString("en-IN")}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${status.className}`}>
                        {status.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button type="button" onClick={() => openEdit(item)} className="rounded-md border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800">
                          Edit ✏️
                        </button>
                        <button type="button" onClick={() => onDelete(item)} className="rounded-md border border-red-500/40 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10">
                          Delete 🗑️
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-400">
          Showing {(page - 1) * PAGE_SIZE + (paged.length ? 1 : 0)}-{(page - 1) * PAGE_SIZE + paged.length} of {filtered.length}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs disabled:opacity-40"
          >
            Prev
          </button>
          <div className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300">
            Page {page} / {pageCount}
          </div>
          <button
            type="button"
            disabled={page >= pageCount}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>

      {modalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4">
          <div className="w-full max-w-2xl rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-slate-100">{editingId ? "Edit Item" : "Add Item"}</h2>
              <button type="button" className="text-slate-400 hover:text-slate-200" onClick={() => setModalOpen(false)}>
                ✕
              </button>
            </div>
            <form onSubmit={submitForm} className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" placeholder="SKU" value={form.sku} onChange={(e) => setForm((f) => ({ ...f, sku: e.target.value }))} required />
              <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" placeholder="Name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
              <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" placeholder="Category" value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))} />
              <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" type="number" placeholder="Stock" value={form.stock} onChange={(e) => setForm((f) => ({ ...f, stock: e.target.value }))} />
              <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" type="number" placeholder="Min Stock" value={form.min_stock} onChange={(e) => setForm((f) => ({ ...f, min_stock: e.target.value }))} />
              <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" type="number" step="0.01" placeholder="Price" value={form.price} onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))} />
              <textarea className="md:col-span-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" rows={3} placeholder="Description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
              <div className="md:col-span-2 mt-2 flex justify-end gap-2">
                <button type="button" className="rounded-lg border border-slate-700 px-4 py-2 text-sm" onClick={() => setModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60">
                  {saving ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
