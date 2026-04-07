import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useEffect } from "react";

import { showToastDedup } from "../../lib/toastDedup.js";
import { gstTotal, parseInr } from "../../utils/format.js";

function buildPeriodRows(analytics) {
  const rev = analytics?.revenue_inr || {};
  const gst = analytics?.gst_collected_inr || {};
  return [
    { period: "Today", revenue: parseInr(rev.today), gst: gstTotal(gst.today) },
    { period: "This week", revenue: parseInr(rev.this_week), gst: gstTotal(gst.this_week) },
    { period: "This month", revenue: parseInr(rev.this_month), gst: gstTotal(gst.this_month) },
  ];
}

export default function FinancialControlTower({ snapshot }) {
  const analytics = snapshot?.analytics || {};
  const profitMonth = snapshot?.business_os?.profit_month || snapshot?.business_summary?.profit_month;
  const rows = buildPeriodRows(analytics);
  const pm = profitMonth?.ok ? profitMonth : null;
  const revToday = parseInr(analytics?.revenue_inr?.today);
  const expenses = pm
    ? parseInr(pm.cogs_inr) +
      parseInr(pm.staff_salaries_monthly_inr) +
      parseInr(pm.operational_expenses_inr) +
      parseInr(pm.maintenance_costs_inr)
    : null;

  useEffect(() => {
    const LARGE_TXN_THRESHOLD_INR = 500000;
    if (revToday > LARGE_TXN_THRESHOLD_INR) {
      showToastDedup({ type: "warning", message: "Large transaction volume today" });
    }
  }, [revToday]);

  return (
    <div className="cc-card">
      <h2>Financial control tower</h2>
      <p className="cc-muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Revenue and GST from bills; P&amp;L strip from month economics (COGS, payroll, opex, maintenance).
      </p>
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
            <XAxis dataKey="period" tick={{ fontSize: 11 }} stroke="#6a6d70" />
            <YAxis tick={{ fontSize: 11 }} stroke="#6a6d70" />
            <Tooltip
              formatter={(v) => [`₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`, ""]}
              contentStyle={{ border: "1px solid #d9d9d9", borderRadius: 4 }}
            />
            <Legend />
            <Bar dataKey="revenue" name="Revenue (INR)" fill="#0a6ed1" radius={[4, 4, 0, 0]} />
            <Bar dataKey="gst" name="GST collected (INR)" fill="#6c8ebf" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {pm && (
        <div
          style={{
            marginTop: 16,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
            gap: 16,
            fontSize: 13,
          }}
        >
          <div>
            <div className="cc-muted" style={{ fontSize: 11 }}>
              Month revenue
            </div>
            <strong>₹{parseInr(pm.revenue_inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</strong>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 11 }}>
              Total costs
            </div>
            <strong>₹{expenses.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</strong>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 11 }}>
              Net profit
            </div>
            <strong style={{ color: parseInr(pm.net_profit_inr) < 0 ? "var(--cc-danger)" : "var(--cc-success)" }}>
              ₹{parseInr(pm.net_profit_inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </strong>
          </div>
        </div>
      )}
    </div>
  );
}
