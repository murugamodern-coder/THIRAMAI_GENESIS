import { useState } from "react";

export default function Dropdown({
  options = [],
  value,
  onChange,
  placeholder = "Select...",
  searchable = false,
  multi = false,
  grouped = false,
}) {
  const [q, setQ] = useState("");
  const selectedValues = multi ? (Array.isArray(value) ? value : []) : [value];
  const needle = q.trim().toLowerCase();
  const filtered =
    !searchable || !needle
      ? options
      : options.filter((o) => String(o?.label || "").toLowerCase().includes(needle));

  return (
    <div className="ui-dropdown">
      {searchable ? (
        <input className="ui-input" placeholder="Search..." value={q} onChange={(e) => setQ(e.target.value)} />
      ) : null}
      <div className="ui-dropdown__menu" role="listbox">
        {filtered.length === 0 ? <p className="cc-muted">No options</p> : null}
        {filtered.map((opt) => {
          const selected = selectedValues.includes(opt.value);
          return (
            <button
              type="button"
              key={opt.value}
              className={`ui-dropdown__item ${selected ? "is-selected" : ""}`}
              onClick={() => {
                if (!multi) return onChange?.(opt.value);
                const next = selected ? selectedValues.filter((x) => x !== opt.value) : [...selectedValues, opt.value];
                onChange?.(next);
              }}
            >
              {grouped && opt.group ? <span className="ui-dropdown__group">{opt.group}</span> : null}
              <span>{opt.label || placeholder}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
