import { useParams } from "react-router-dom";

export default function PayrollPage() {
  const { orgId } = useParams();

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 className="cc-page-title">Payroll Dashboard for Organization {orgId}</h1>

      {/* Top Stats */}
      <div className="cc-card" style={{ display: "flex", justifyContent: "space-between", marginBottom: 24 }}>
        <div><h3>Total Employees</h3><p>8</p></div>
        <div><h3>This month payroll</h3><p>₹1,60,000</p></div>
        <div><h3>PF deduction</h3><p>₹19,200</p></div>
        <div><h3>Net payout</h3><p>₹1,40,800</p></div>
      </div>

      {/* Employee Payroll Table */}
      <div className="cc-card" style={{ marginBottom: 24 }}>
        <h3>Employee Payroll</h3>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Designation</th>
              <th>Basic</th>
              <th>HRA</th>
              <th>Gross</th>
              <th>PF</th>
              <th>Net</th>
            </tr>
          </thead>
          <tbody>
            {[{
              employee: "Ramu K",
              designation: "Operator",
              basic: "₹15,000",
              hra: "₹6,000",
              gross: "₹21,000",
              pf: "₹1,800",
              net: "₹19,200",
            }, {
              employee: "Selvi M",
              designation: "Supervisor",
              basic: "₹20,000",
              hra: "₹8,000",
              gross: "₹28,000",
              pf: "₹2,400",
              net: "₹25,600",
            }, {
              employee: "Kannan R",
              designation: "Helper",
              basic: "₹12,000",
              hra: "₹4,800",
              gross: "₹16,800",
              pf: "₹1,440",
              net: "₹15,360",
            }, {
              employee: "Priya S",
              designation: "Accountant",
              basic: "₹18,000",
              hra: "₹7,200",
              gross: "₹25,200",
              pf: "₹2,160",
              net: "₹23,040",
            }].map(emp => (
              <tr key={emp.employee} style={{ borderBottom: "1px solid #dde" }}>
                <td>{emp.employee}</td>
                <td>{emp.designation}</td>
                <td>{emp.basic}</td>
                <td>{emp.hra}</td>
                <td>{emp.gross}</td>
                <td>{emp.pf}</td>
                <td>{emp.net}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Bottom Buttons */}
      <div style={{ display: "flex", gap: 12 }}>
        <button className="cc-btn cc-btn-primary">Run Payroll</button>
        <button className="cc-btn">Export Excel</button>
        <button className="cc-btn">Generate Payslips</button>
      </div>
    </div>
  );
}