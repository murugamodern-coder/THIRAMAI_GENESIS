import { useState } from "react";
import { useParams } from "react-router-dom";

export default function ReportsPage() {
  const { orgId } = useParams();
  const [selectedReport, setSelectedReport] = useState("P&L Statement");

  const reports = [
    "P&L Statement",
    "Balance Sheet",
    "Cash Flow",
    "GST Report",
    "Payroll Report",
  ];

  return (
    <div style={{ display: "flex", height: "100%", marginTop: "20px" }}>
      {/* Sidebar Navigation */}
      <div style={{ width: "200px", borderRight: "1px solid #dde", paddingRight: "10px" }}>
        <p className="cc-muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
          Org {orgId ?? "—"}
        </p>
        {reports.map((report) => (
          <div
            key={report}
            className={`cc-card ${selectedReport === report ? "cc-card-active" : ""}`}
            onClick={() => setSelectedReport(report)}
            style={{ padding: "10px", marginBottom: "10px", cursor: "pointer" }}
          >
            {report}
          </div>
        ))}
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, padding: "20px" }}>
        {selectedReport === "P&L Statement" && (
          <div>
            <h1 className="cc-page-title">Profit & Loss Statement</h1>
            <p>Period: Apr 2024 - Mar 2025</p>
            <div style={{ marginBottom: "20px" }}>
              <button className="cc-btn">Export PDF</button>
              <button className="cc-btn">Export Excel</button>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                <tr><td><strong>REVENUE</strong></td></tr>
                <tr><td>Sales Revenue</td><td>₹12,40,000</td></tr>
                <tr><td>Other Income</td><td>₹50,000</td></tr>
                <tr><td><strong>Total Revenue</strong></td><td>₹12,90,000</td></tr>

                <tr><td><strong>COST OF GOODS SOLD</strong></td></tr>
                <tr><td>Purchases</td><td>₹8,00,000</td></tr>
                <tr><td><strong>Total COGS</strong></td><td>₹8,00,000</td></tr>

                <tr><td><strong>GROSS PROFIT</strong></td><td>₹4,90,000</td></tr>
                <tr><td>Gross Margin %</td><td>38%</td></tr>

                <tr><td><strong>OPERATING EXPENSES</strong></td></tr>
                <tr><td>Salaries</td><td>₹2,00,000</td></tr>
                <tr><td>Rent</td><td>₹50,000</td></tr>
                <tr><td>Electricity</td><td>₹30,000</td></tr>
                <tr><td><strong>Total Expenses</strong></td><td>₹2,80,000</td></tr>

                <tr><td><strong>NET PROFIT</strong></td><td>₹2,10,000</td></tr>
                <tr><td>Net Margin %</td><td>16.3%</td></tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
