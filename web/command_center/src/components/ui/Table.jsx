import { useState } from "react";
import EmptyState from "./EmptyState.jsx";
import Skeleton from "./Skeleton.jsx";

export default function Table({
  columns = [],
  rows = [],
  loading = false,
  rowKey = "id",
  selectable = false,
  onSelectionChange,
  pageSize = 10,
}) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const [selected, setSelected] = useState([]);
  const start = (page - 1) * pageSize;

  const list = Array.isArray(rows) ? [...rows] : [];
  if (sort.key) {
    list.sort((a, b) => {
      const av = a?.[sort.key];
      const bv = b?.[sort.key];
      if (av === bv) return 0;
      if (sort.dir === "asc") return av > bv ? 1 : -1;
      return av < bv ? 1 : -1;
    });
  }
  const sortedRows = list;

  const pageRows = sortedRows.slice(start, start + pageSize);
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));

  function toggleSelect(k) {
    const next = selected.includes(k) ? selected.filter((x) => x !== k) : [...selected, k];
    setSelected(next);
    onSelectionChange?.(next);
  }

  return (
    <div className="ui-table-wrap">
      <table className="cc-table">
        <thead>
          <tr>
            {selectable ? <th /> : null}
            {columns.map((c) => (
              <th key={c.key}>
                <button
                  type="button"
                  className="ui-table-sort"
                  onClick={() =>
                    setSort((prev) => ({
                      key: c.key,
                      dir: prev.key === c.key && prev.dir === "asc" ? "desc" : "asc",
                    }))
                  }
                >
                  {c.label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={columns.length + (selectable ? 1 : 0)}>
                <Skeleton variant="table" />
              </td>
            </tr>
          ) : pageRows.length === 0 ? (
            <tr>
              <td colSpan={columns.length + (selectable ? 1 : 0)}>
                <EmptyState title="No records" description="There is no data to display." />
              </td>
            </tr>
          ) : (
            pageRows.map((row) => {
              const key = row?.[rowKey];
              return (
                <tr key={key}>
                  {selectable ? (
                    <td>
                      <input type="checkbox" checked={selected.includes(key)} onChange={() => toggleSelect(key)} />
                    </td>
                  ) : null}
                  {columns.map((c) => (
                    <td key={`${key}-${c.key}`}>{c.render ? c.render(row) : row?.[c.key] ?? "—"}</td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
      <div className="ui-table-pagination">
        <button type="button" className="cc-btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
          Prev
        </button>
        <span className="cc-muted">
          Page {page} / {totalPages}
        </span>
        <button type="button" className="cc-btn" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
          Next
        </button>
      </div>
    </div>
  );
}
