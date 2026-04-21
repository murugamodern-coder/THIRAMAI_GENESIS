import { useState } from "react";
import { useParams } from "react-router-dom";

const TYPE_COLORS = {
  Assets: "#3b82f6",
  Liabilities: "#ef4444", 
  Income: "#10b981",
  Expenses: "#f59e0b",
  Equity: "#8b5cf6",
};

const SAMPLE_ACCOUNTS = [
  { id:1, type:"Assets", name:"Cash in Hand", balance:50000 },
  { id:2, type:"Assets", name:"Bank Account", balance:200000 },
  { id:3, type:"Assets", name:"Accounts Receivable", balance:80000 },
  { id:4, type:"Liabilities", name:"Accounts Payable", balance:30000 },
  { id:5, type:"Liabilities", name:"GST Payable", balance:15000 },
  { id:6, type:"Income", name:"Sales Revenue", balance:500000 },
  { id:7, type:"Expenses", name:"Salaries", balance:200000 },
  { id:8, type:"Expenses", name:"Rent", balance:50000 },
  { id:9, type:"Equity", name:"Owner Capital", balance:300000 },
];

export default function ChartOfAccountsPage() {
  const { orgId } = useParams();
  const [expanded, setExpanded] = useState(
    Object.fromEntries(Object.keys(TYPE_COLORS).map(t => [t, true]))
  );

  const grouped = Object.keys(TYPE_COLORS).map(type => ({
    type,
    color: TYPE_COLORS[type],
    accounts: SAMPLE_ACCOUNTS.filter(a => a.type === type),
    total: SAMPLE_ACCOUNTS.filter(a => a.type === type)
      .reduce((s, a) => s + a.balance, 0),
  }));

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "24px 16px" }}>
      <div style={{ display:"flex", justifyContent:"space-between", 
                    alignItems:"center", marginBottom:16 }}>
        <div>
          <h1 className="cc-page-title" style={{ margin: 0 }}>
            Chart of Accounts
          </h1>
          <p className="cc-muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
            Organization {orgId ?? "—"}
          </p>
        </div>
        <button type="button" className="cc-btn cc-btn-primary">
          + Add Account
        </button>
      </div>

      {grouped.map(g => (
        <div key={g.type} className="cc-card" style={{ marginBottom:12 }}>
          <div
            onClick={() => setExpanded(e => ({...e, [g.type]: !e[g.type]}))}
            style={{ display:"flex", justifyContent:"space-between",
                     alignItems:"center", cursor:"pointer" }}
          >
            <div style={{ display:"flex", alignItems:"center", gap:10 }}>
              <div style={{ width:12, height:12, borderRadius:9999,
                           background:g.color }} />
              <span style={{ fontWeight:700, fontSize:16 }}>{g.type}</span>
            </div>
            <div style={{ display:"flex", alignItems:"center", gap:12 }}>
              <span style={{ fontWeight:600, color:g.color }}>
                ₹{g.total.toLocaleString("en-IN")}
              </span>
              <span>{expanded[g.type] ? "▲" : "▼"}</span>
            </div>
          </div>

          {expanded[g.type] && (
            <div style={{ marginTop:12, borderTop:"1px solid var(--cc-border)",
                         paddingTop:12 }}>
              {g.accounts.map(a => (
                <div key={a.id}
                  style={{ display:"flex", justifyContent:"space-between",
                           padding:"8px 0", borderBottom:"1px solid var(--cc-border)" }}>
                  <span style={{ paddingLeft:22 }}>{a.name}</span>
                  <span className="cc-muted">
                    ₹{a.balance.toLocaleString("en-IN")}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}