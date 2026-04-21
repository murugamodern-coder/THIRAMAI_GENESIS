import Badge from "../ui/Badge.jsx";

const ENGINE_KEYS = [
  { key: "macro", label: "Macro" },
  { key: "orderFlow", label: "Order Flow" },
  { key: "fundamentals", label: "Fundamentals" },
  { key: "geopolitics", label: "Geopolitics" },
];

function toVariant(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("error") || normalized.includes("offline")) return "error";
  if (normalized.includes("warming") || normalized.includes("monitor")) return "warning";
  if (normalized.includes("active") || normalized.includes("live") || normalized.includes("tracked")) return "success";
  return "neutral";
}

export default function FourPointEngineStrip({ engine }) {
  const source = engine && typeof engine === "object" ? engine : {};
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
      {ENGINE_KEYS.map((entry) => (
        <div key={entry.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <span className="cc-muted" style={{ fontSize: 12 }}>
            {entry.label}
          </span>
          <Badge variant={toVariant(source[entry.key])} size="sm">
            {source[entry.key] || "pending"}
          </Badge>
        </div>
      ))}
    </div>
  );
}
