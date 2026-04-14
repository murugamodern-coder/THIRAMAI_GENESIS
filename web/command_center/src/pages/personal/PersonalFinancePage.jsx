import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createPersonalBudget,
  createPersonalExpense,
  createPersonalLoan,
  fetchBusinessGstSuggest,
  fetchPersonalBudgets,
  fetchPersonalExpenses,
  fetchPersonalLoans,
  postBusinessBankStatementImport,
  postPersonalExpenseScanConfirm,
  postPersonalExpenseScanPreview,
} from "../../api/commandCenterApi.js";
import { safeAsync } from "../../lib/safeAsync.js";

const EXPENSE_CATEGORIES = [
  { value: "food", label: "Food" },
  { value: "transport", label: "Transport" },
  { value: "materials", label: "Materials" },
  { value: "utilities", label: "Utilities" },
  { value: "health", label: "Health" },
  { value: "education", label: "Education" },
  { value: "housing", label: "Housing" },
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

  const [scanLoading, setScanLoading] = useState(false);
  const [scanToken, setScanToken] = useState(null);
  const [scanPreview, setScanPreview] = useState(null);
  const [scanEditAmount, setScanEditAmount] = useState("");
  const [scanEditCategory, setScanEditCategory] = useState("food");
  const [scanEditVendor, setScanEditVendor] = useState("");
  const [bankImportMsg, setBankImportMsg] = useState(null);
  const [gstProbe, setGstProbe] = useState({ hsn: "", desc: "" });
  const [gstOut, setGstOut] = useState(null);

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

  const onReceiptSelected = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setMessage(null);
    setScanLoading(true);
    setScanToken(null);
    setScanPreview(null);
    try {
      const data = await postPersonalExpenseScanPreview(f);
      setScanToken(data.preview_token || null);
      const prev = data.preview || data.scan || null;
      setScanPreview(prev);
      if (prev?.amount != null) setScanEditAmount(String(prev.amount));
      if (prev?.category) setScanEditCategory(prev.category);
      if (prev?.vendor_name) setScanEditVendor(prev.vendor_name);
      setMessage(data.ok ? "Receipt scanned — review and confirm." : "Scan uncertain — edit fields before confirm.");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Scan failed.");
    } finally {
      setScanLoading(false);
    }
  };

  const onConfirmScan = async () => {
    if (!scanToken) {
      setMessage("Scan a receipt first.");
      return;
    }
    const amount = Number(scanEditAmount);
    if (!amount || amount <= 0) {
      setMessage("Valid amount required.");
      return;
    }
    setScanLoading(true);
    setMessage(null);
    try {
      await postPersonalExpenseScanConfirm(
        {
          preview_token: scanToken,
          amount,
          category: scanEditCategory,
          vendor_name: scanEditVendor || undefined,
        },
        vaultPass || undefined,
      );
      setScanToken(null);
      setScanPreview(null);
      await load();
      setMessage("Expense saved from receipt (source: auto_scan).");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Confirm failed.");
    } finally {
      setScanLoading(false);
    }
  };

  const onBankImport = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBankImportMsg(null);
    setScanLoading(true);
    try {
      const out = await postBusinessBankStatementImport(f);
      const n = (out.created || []).length;
      const rev = (out.needs_review || []).length;
      setBankImportMsg(`Imported ${n} expense rows. ${rev ? `${rev} need review.` : ""}`);
    } catch (err) {
      setBankImportMsg(err?.response?.data?.detail || err?.message || "Import failed.");
    } finally {
      setScanLoading(false);
    }
  };

  const onGstProbe = async () => {
    setGstOut(null);
    try {
      const d = await fetchBusinessGstSuggest({ hsn: gstProbe.hsn, description: gstProbe.desc });
      setGstOut(d?.suggestion || null);
    } catch (err) {
      setGstOut({ error: err?.response?.data?.detail || err?.message });
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

      <section className="personal-os-card" style={{ marginBottom: 20 }}>
        <h2 className="personal-os-card-title">Auto accounting (Upgrade 5)</h2>
        <p className="personal-os-sub" style={{ marginTop: 0 }}>
          Receipt scan uses Groq Vision or Gemini (API keys). Confirm before saving. Bank import posts to your active
          organization&apos;s operational expenses.
        </p>
        <div className="personal-os-form-grid">
          <label className="personal-os-label personal-os-label--full">
            Receipt image
            <input type="file" accept="image/*" className="cc-input" disabled={scanLoading} onChange={onReceiptSelected} />
          </label>
          {scanPreview ? (
            <>
              <div className="personal-os-label personal-os-label--full" style={{ fontSize: 14 }}>
                {scanPreview.needs_review ? (
                  <strong style={{ color: "#b45309" }}>Needs review — verify amounts.</strong>
                ) : (
                  <span className="cc-muted">Model confidence: {scanPreview.confidence ?? "—"}</span>
                )}
                {scanPreview.raw_summary ? (
                  <div className="cc-muted" style={{ marginTop: 6 }}>
                    {String(scanPreview.raw_summary).slice(0, 240)}
                  </div>
                ) : null}
              </div>
              <label className="personal-os-label">
                Amount (INR)
                <input className="cc-input" type="number" step="0.01" value={scanEditAmount} onChange={(e) => setScanEditAmount(e.target.value)} />
              </label>
              <label className="personal-os-label">
                Category
                <select className="cc-select" value={scanEditCategory} onChange={(e) => setScanEditCategory(e.target.value)}>
                  {EXPENSE_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="personal-os-label personal-os-label--full">
                Vendor
                <input className="cc-input" value={scanEditVendor} onChange={(e) => setScanEditVendor(e.target.value)} />
              </label>
              <button type="button" className="cc-btn cc-btn-primary" disabled={scanLoading} onClick={onConfirmScan}>
                Confirm &amp; save expense
              </button>
            </>
          ) : null}
        </div>
        <hr style={{ margin: "16px 0", opacity: 0.2 }} />
        <h3 className="personal-os-card-title" style={{ fontSize: 16 }}>
          Business — bank statement (CSV / PDF)
        </h3>
        <input type="file" accept=".csv,.pdf,text/csv,application/pdf" className="cc-input" disabled={scanLoading} onChange={onBankImport} />
        {bankImportMsg ? <div style={{ marginTop: 8 }}>{bankImportMsg}</div> : null}
        <hr style={{ margin: "16px 0", opacity: 0.2 }} />
        <h3 className="personal-os-card-title" style={{ fontSize: 16 }}>
          GST hint (HSN + description)
        </h3>
        <div className="personal-os-form-grid">
          <label className="personal-os-label">
            HSN
            <input className="cc-input" value={gstProbe.hsn} onChange={(e) => setGstProbe((p) => ({ ...p, hsn: e.target.value }))} placeholder="8517" />
          </label>
          <label className="personal-os-label personal-os-label--full">
            Description
            <input className="cc-input" value={gstProbe.desc} onChange={(e) => setGstProbe((p) => ({ ...p, desc: e.target.value }))} />
          </label>
          <button type="button" className="cc-btn" onClick={onGstProbe}>
            Suggest rate
          </button>
        </div>
        {gstOut && !gstOut.error ? (
          <pre style={{ marginTop: 8, fontSize: 12, overflow: "auto" }}>{JSON.stringify(gstOut, null, 2)}</pre>
        ) : gstOut?.error ? (
          <div className="cc-muted">{gstOut.error}</div>
        ) : null}
      </section>

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
