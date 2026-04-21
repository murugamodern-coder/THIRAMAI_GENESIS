import { useState } from "react";
import Card from "../components/ui/Card.jsx";
import Button from "../components/ui/Button.jsx";
import Stat from "../components/ui/Stat.jsx";

const TABS = ["Revenue", "Inventory", "Production"];

export default function AnalyticsPage() {
  const [tab, setTab] = useState("Revenue");
  const [range, setRange] = useState("30d");

  const stats = [
    { label: "This period", value: 1240000, trend: 14 },
    { label: "Last period", value: 1080000, trend: -2 },
    { label: "Delta", value: 160000, trend: 18 },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 16 }}>
        <h1 className="cc-page-title" style={{ margin: 0 }}>Analytics</h1>
        <div style={{ display: "flex", gap: 8 }}>
          {["7d", "30d", "90d", "custom"].map((x) => (
            <Button key={x} size="sm" variant={range === x ? "primary" : "secondary"} onClick={() => setRange(x)}>
              {x}
            </Button>
          ))}
          <Button variant="ghost" size="sm">Export CSV</Button>
          <Button variant="ghost" size="sm">Export PDF</Button>
        </div>
      </div>

      <Card variant="gradient" title="KPI comparison" subtitle={`${tab} • ${range}`}>
        <div className="cc-kpi-row" style={{ marginBottom: 0 }}>
          {stats.map((s) => (
            <Stat key={s.label} label={s.label} value={s.value} trend={s.trend} sparkline="▲ trendline" />
          ))}
        </div>
      </Card>

      <Card title="Metrics view">
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          {TABS.map((t) => (
            <Button key={t} variant={tab === t ? "primary" : "secondary"} size="sm" onClick={() => setTab(t)}>
              {t}
            </Button>
          ))}
        </div>
        <div className="ui-skeleton" style={{ height: 280 }} aria-label="Chart placeholder" />
      </Card>
    </div>
  );
}
