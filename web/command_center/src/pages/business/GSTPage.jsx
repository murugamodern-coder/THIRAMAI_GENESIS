import { useParams } from "react-router-dom";

export default function GSTPage() {
  const { orgId } = useParams();

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 className="cc-page-title">GST Dashboard for Organization {orgId}</h1>

      {/* Top Cards Row */}
      <div style={{ display: "flex", gap: 16, marginBottom: 24 }}>
        <div className="cc-card"><h3>Tax Collected</h3><p>₹45,000</p></div>
        <div className="cc-card"><h3>Input Credit</h3><p>₹18,000</p></div>
        <div className="cc-card"><h3>Net Payable</h3><p>₹27,000</p></div>
        <div className="cc-card"><h3>Next Due</h3><p>20th Dec 2024</p></div>
      </div>

      {/* GSTR-3B Summary Table */}
      <div className="cc-card" style={{ marginBottom: 24 }}>
        <h3>GSTR-3B Summary</h3>
        <table>
          <thead>
            <tr>
              <th>Description</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Outward supplies (Sales)</td><td>₹5,00,000</td></tr>
            <tr><td>CGST collected</td><td>₹22,500</td></tr>
            <tr><td>SGST collected</td><td>₹22,500</td></tr>
            <tr><td>Input tax credit</td><td>₹18,000</td></tr>
            <tr><td>Net GST payable</td><td>₹27,000</td></tr>
          </tbody>
        </table>
      </div>

      {/* Filing Status List */}
      <div className="cc-card">
        <h3>Filing Status</h3>
        <ul>
          <li>GSTR-1 Nov 2024 → Filed ✅</li>
          <li>GSTR-3B Nov 2024 → Filed ✅</li>
          <li>GSTR-1 Dec 2024 → Pending ⚠️</li>
          <li>GSTR-3B Dec 2024 → Due 20 Jan ⏰</li>
        </ul>
      </div>
    </div>
  );
}