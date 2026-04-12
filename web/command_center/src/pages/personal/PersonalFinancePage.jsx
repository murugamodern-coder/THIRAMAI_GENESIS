import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createPersonalBudget,
  createPersonalExpense,
  createPersonalLoan,
  fetchPersonalBudgets,
  fetchPersonalExpenses,
  fetchPersonalLoans,
} from "../../api/commandCenterApi.js";
import { safeAsync } from "../../lib/safeAsync.js";

const EXPENSE_CATEGORIES = [
  { value: "loans", label: "Loans" },
  { value: "vehicle", label: "Vehicle" },
  { value: "digital_bills", label: "Digital bills" },
  { value: "personal", label: "Personal" },
  { value: "worker_payment", label: "Worker payment" },
  { value: "other", label: "Other" },
];

const LOAN_KINDS = [
  { value: "unsecured", label: "Unsecured" },
  { value: "secured", label: "Secured" },
  { value: "emi", label: "EMI" },
  { value: "jewel", label: "Jewel loan" },
  { value: "chits", label: "Chits" },
  { value: "other", label: "Other" },
];

function firstOfMonthISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function endOfMonthISO() {
  const d = new Date();
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return last.toISOString().slice(0, 10);
}

export default function PersonalFinancePage() {
  const [vaultPass, setVaultPass] = useState("");
  const [expenses, setExpenses] = useState([]);
  const [loans, setLoans] = useState([]);
  const [budgets, setBudgets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);

  const [expAmount, setExpAmount] = useState("");
  const [expCategory, setExpCategory] = useState("personal");
  const [expSub, setExpSub] = useState("");
  const [expTitle, setExpTitle] = useState("");

  const [loanName, setLoanName] = useState("");
  const [loanKind, setLoanKind] = useState("emi");
  const [loanLender, setLoanLender] = useState("");
  const [loanPrincipal, setLoanPrincipal] = useState("");
  const [loanEmi, setLoanEmi] = useState("");
  const [loanDue, setLoanDue] = useState("");

  const [budCat, setBudCat] = useState("personal");
  const [budAmt, setBudAmt] = useState("");
  const [budStart, setBudStart] = useState(firstOfMonthISO());
  const [budEnd, setBudEnd] = useState(endOfMonthISO());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [e, l, b] = await Promise.all([
        fetchPersonalExpenses(80),
        fetchPersonalLoans(),
        fetchPersonalBudgets(),
      ]);
      setExpenses(e?.items || []);
      setLoans(l?.items || []);
      setBudgets(b?.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    safeAsync(load, { toast: false })();
  }, [load]);

  const onAddExpense = async (e) => {
    e.preventDefault();
    setMessage(null);
    const amount = Number(expAmount);
    if (!amount || amount <= 0) {
      setMessage("Enter a valid amount.");
      return;
    }
    try {
      await createPersonalExpense(
        {
          amount,
          currency: "INR",
          category: expCategory,
          subcategory: expSub,
          title: expTitle,
        },
        vaultPass || undefined,
      );
      setExpAmount("");
      setExpTitle("");
      await load();
      setMessage("Expense saved.");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Failed.");
    }
  };

  const onAddLoan = async (e) => {
    e.preventDefault();
    setMessage(null);
    if (!loanName.trim()) {
      setMessage("Loan name required.");
      return;
    }
    try {
      await createPersonalLoan(
        {
          display_name: loanName.trim(),
          loan_kind: loanKind,
          lender: loanLender || null,
          principal_outstanding: loanPrincipal ? Number(loanPrincipal) : null,
          emi_amount: loanEmi ? Number(loanEmi) : null,
          next_due_date: loanDue || null,
        },
        vaultPass || undefined,
      );
      setLoanName("");
      setLoanLender("");
      setLoanPrincipal("");
      setLoanEmi("");
      setLoanDue("");
      await load();
      setMessage("Loan row saved.");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Failed.");
    }
  };

  const onAddBudget = async (e) => {
    e.preventDefault();
    setMessage(null);
    const amount = Number(budAmt);
    if (!amount || amount <= 0) {
      setMessage("Budget amount required.");
      return;
    }
    try {
      await createPersonalBudget({
        period_start: budStart,
        period_end: budEnd,
        category: budCat,
        subcategory: "",
        budget_amount: amount,
        currency: "INR",
        overspend_alert_pct: 15,
      });
      setBudAmt("");
      await load();
      setMessage("Budget envelope saved.");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Failed.");
    }
  };

  const expenseRows = useMemo(
    () =>
      expenses.map((x) => (
        <tr key={x.id}>
          <td>{x.spent_at?.slice(0, 16)}</td>
          <td>{x.category}</td>
          <td>{x.subcategory || "—"}</td>
          <td style={{ textAlign: "right" }}>{x.amount}</td>
          <td className="cc-muted">{x.title || "—"}</td>
        </tr>
      )),
    [expenses],
  );

  return (
    <div className="personal-os-page personal-os-touch">
      <header className="personal-os-section-head">
        <h1 className="personal-os-title">Financial command center</h1>
        <p className="personal-os-sub">Personal cash flow, loans, and budgets (encrypted notes when vault is set).</p>
      </header>

      <label className="personal-os-label personal-os-inline-vault">
        Vault passphrase (optional)
        <input
          type="password"
          className="cc-input personal-os-input personal-os-input--narrow"
          value={vaultPass}
          onChange={(e) => setVaultPass(e.target.value)}
          autoComplete="off"
        />
      </label>

      {message && <div className="personal-os-banner">{message}</div>}

      <div className="personal-os-finance-grid">
        <form className="personal-os-card" onSubmit={onAddExpense}>
          <h2 className="personal-os-card-title">Log expense</h2>
          <div className="personal-os-form-grid">
            <label className="personal-os-label">
              Amount (INR)
              <input className="cc-input" type="number" step="0.01" min="0" value={expAmount} onChange={(e) => setExpAmount(e.target.value)} required />
            </label>
            <label className="personal-os-label">
              Category
              <select className="cc-select" value={expCategory} onChange={(e) => setExpCategory(e.target.value)}>
                {EXPENSE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="personal-os-label">
              Subcategory
              <input className="cc-input" value={expSub} onChange={(e) => setExpSub(e.target.value)} placeholder="e.g. fuel, OTT, medical" />
            </label>
            <label className="personal-os-label personal-os-label--full">
              Note
              <input className="cc-input" value={expTitle} onChange={(e) => setExpTitle(e.target.value)} placeholder="Short description" />
            </label>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" style={{ marginTop: 12 }}>
            Save expense
          </button>
        </form>

        <form className="personal-os-card" onSubmit={onAddLoan}>
          <h2 className="personal-os-card-title">Loan / EMI tracker</h2>
          <div className="personal-os-form-grid">
            <label className="personal-os-label personal-os-label--full">
              Display name
              <input className="cc-input" value={loanName} onChange={(e) => setLoanName(e.target.value)} required />
            </label>
            <label className="personal-os-label">
              Kind
              <select className="cc-select" value={loanKind} onChange={(e) => setLoanKind(e.target.value)}>
                {LOAN_KINDS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="personal-os-label">
              Lender
              <input className="cc-input" value={loanLender} onChange={(e) => setLoanLender(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Total outstanding (principal)
              <input className="cc-input" type="number" step="0.01" min="0" value={loanPrincipal} onChange={(e) => setLoanPrincipal(e.target.value)} placeholder="Optional" />
            </label>
            <label className="personal-os-label">
              EMI amount
              <input className="cc-input" type="number" step="0.01" min="0" value={loanEmi} onChange={(e) => setLoanEmi(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Next due
              <input className="cc-input" type="date" value={loanDue} onChange={(e) => setLoanDue(e.target.value)} />
            </label>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" style={{ marginTop: 12 }}>
            Save loan
          </button>
        </form>

        <form className="personal-os-card" onSubmit={onAddBudget}>
          <h2 className="personal-os-card-title">Budget envelope</h2>
          <div className="personal-os-form-grid">
            <label className="personal-os-label">
              Category
              <select className="cc-select" value={budCat} onChange={(e) => setBudCat(e.target.value)}>
                {EXPENSE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="personal-os-label">
              Cap (INR)
              <input className="cc-input" type="number" step="1" min="0" value={budAmt} onChange={(e) => setBudAmt(e.target.value)} required />
            </label>
            <label className="personal-os-label">
              Period start
              <input className="cc-input" type="date" value={budStart} onChange={(e) => setBudStart(e.target.value)} required />
            </label>
            <label className="personal-os-label">
              Period end
              <input className="cc-input" type="date" value={budEnd} onChange={(e) => setBudEnd(e.target.value)} required />
            </label>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" style={{ marginTop: 12 }}>
            Save budget
          </button>
        </form>
      </div>

      <section className="personal-os-card personal-os-table-card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="personal-os-card-title" style={{ margin: 0 }}>
            Recent expenses
          </h2>
          <button type="button" className="cc-btn" onClick={() => load()} disabled={loading}>
            Refresh
          </button>
        </div>
        <div className="personal-os-table-wrap">
          <table className="personal-os-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Category</th>
                <th>Sub</th>
                <th style={{ textAlign: "right" }}>Amount</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {expenseRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="personal-os-empty-cta">
                    No expenses yet → add one with the form above.
                  </td>
                </tr>
              ) : (
                expenseRows
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="personal-os-two-col">
        <section className="personal-os-card">
          <h2 className="personal-os-card-title">Loans</h2>
          <ul className="personal-os-list personal-os-list--plain">
            {loans.length === 0 && <li className="personal-os-empty-cta">No loans yet → use the loan form above.</li>}
            {loans.map((r) => (
              <li key={r.id}>
                <strong>{r.display_name}</strong> · {r.loan_kind}
                <div className="cc-muted" style={{ fontSize: 12 }}>
                  Principal {r.principal_outstanding ?? "—"} · Next {r.next_due_date || "—"} · EMI {r.emi_amount ?? "—"} ·{" "}
                  {r.is_closed ? "closed" : "open"}
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="personal-os-card">
          <h2 className="personal-os-card-title">Budgets</h2>
          <ul className="personal-os-list personal-os-list--plain">
            {budgets.length === 0 && <li className="cc-muted">No budgets.</li>}
            {budgets.map((r) => (
              <li key={r.id}>
                <strong>{r.category}</strong> {r.budget_amount} {r.currency}
                <div className="cc-muted" style={{ fontSize: 12 }}>
                  {r.period_start} → {r.period_end} · alert +{r.overspend_alert_pct}%
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
