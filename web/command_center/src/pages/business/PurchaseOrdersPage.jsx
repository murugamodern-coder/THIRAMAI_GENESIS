import { useParams } from "react-router-dom";

const STATUS_COLORS = {
  Draft: "#a0aec0",
  Sent: "#4299e1",
  Confirmed: "#f6ad55",
  Received: "#48bb78",
  Cancelled: "#f56565",
};

export default function PurchaseOrdersPage() {
  const { orgId } = useParams();

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      {/* Top Stats Row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 className="cc-page-title" style={{ margin: 0 }}>Purchase Orders for Organization {orgId}</h1>
        <button className="cc-btn cc-btn-primary">+ New PO</button>
      </div>

      <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
        <div className="cc-card"><h3>Total POs</h3><p>12</p></div>
        <div className="cc-card"><h3>Pending</h3><p>5</p></div>
        <div className="cc-card"><h3>This month value</h3><p>₹2,40,000</p></div>
      </div>

      {/* Status Filter Tabs */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        {Object.keys(STATUS_COLORS).map((status) => (
          <button key={status} className="cc-btn" style={{ color: STATUS_COLORS[status] }}>{status}</button>
        ))}
      </div>

      {/* PO List Table */}
      <div className="cc-card">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>PO Number</th>
              <th>Vendor</th>
              <th>Date</th>
              <th>Amount</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {[{
              number: "PO/2425/001",
              vendor: "ABC Suppliers",
              date: "10 Jan",
              amount: "₹45,000",
              status: "Confirmed",
            }, {
              number: "PO/2425/002",
              vendor: "XYZ Trading",
              date: "12 Jan",
              amount: "₹28,000",
              status: "Sent",
            }, {
              number: "PO/2425/003",
              vendor: "Kumar & Co",
              date: "15 Jan",
              amount: "₹67,000",
              status: "Draft",
            }, {
              number: "PO/2425/004",
              vendor: "Ram Traders",
              date: "16 Jan",
              amount: "₹35,000",
              status: "Received",
            }].map(po => (
              <tr key={po.number} style={{ borderBottom: "1px solid #dde" }}>
                <td>{po.number}</td>
                <td>{po.vendor}</td>
                <td>{po.date}</td>
                <td>{po.amount}</td>
                <td style={{ color: STATUS_COLORS[po.status] }}>{po.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}