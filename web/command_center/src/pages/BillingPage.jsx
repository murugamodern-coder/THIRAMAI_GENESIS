import { useCallback, useEffect, useState } from "react";

import { createStructuredInvoice, fetchInvoices, recordPayment } from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

export default function BillingPage() {
  const [invoices, setInvoices] = useState([]);
  const [err, setErr] = useState(null);
  const [pay, setPay] = useState({ invoice_id: "", amount_inr: "", method: "bank", reference: "" });
  const [invForm, setInvForm] = useState({
    description: "Service",
    quantity: "1",
    unit_price_pre_tax: "100",
    gst_rate_percent: "18",
  });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const out = await fetchInvoices(200);
      setInvoices(out?.invoices || []);
    } catch (e) {
      const d = e?.response?.data?.detail;
      const msg = typeof d === "string" ? d : e?.message || "Load failed";
      setErr(msg);
      showToastDedup({
        type: "error",
        message: "Failed to load invoices",
        actionLabel: "Retry",
        onAction: () => load(),
      });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function submitPayment(e) {
    e.preventDefault();
    setErr(null);
    try {
      const payload = {
        invoice_id: Number(pay.invoice_id),
        amount_inr: Number(pay.amount_inr),
        method: pay.method,
        reference: pay.reference || null,
      };
      const LARGE_PAYMENT_THRESHOLD_INR = 250000;
      if (payload.amount_inr > LARGE_PAYMENT_THRESHOLD_INR) {
        showToastDedup({ type: "warning", message: "Large payment recorded" });
      }
      await recordPayment(payload);
      setPay({ invoice_id: "", amount_inr: "", method: "bank", reference: "" });
      showToastDedup({ type: "success", message: "Payment recorded" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      const msg = typeof d === "string" ? d : "Payment failed";
      setErr(msg);
      showToastDedup({
        type: "error",
        message: "Payment failed",
        actionLabel: "Retry",
        onAction: () =>
          recordPayment({
            invoice_id: Number(pay.invoice_id),
            amount_inr: Number(pay.amount_inr),
            method: pay.method,
            reference: pay.reference || null,
          }).then(() => load()),
      });
    }
  }

  async function createInvoice(e) {
    e.preventDefault();
    setErr(null);
    try {
      await createStructuredInvoice({
        invoice_no: "",
        invoice_date: "",
        lines: [
          {
            description: invForm.description.trim() || "Line",
            quantity: Number(invForm.quantity) || 1,
            unit_price_pre_tax: Number(invForm.unit_price_pre_tax) || 0,
            gst_rate_percent: Number(invForm.gst_rate_percent) || 0,
          },
        ],
      });
      showToastDedup({ type: "success", message: "Invoice created" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      const msg = typeof d === "string" ? d : "Invoice create failed";
      setErr(msg);
      showToastDedup({
        type: "error",
        message: "Invoice create failed",
        actionLabel: "Retry",
        onAction: () =>
          createStructuredInvoice({
            invoice_no: "",
            invoice_date: "",
            lines: [
              {
                description: invForm.description.trim() || "Line",
                quantity: Number(invForm.quantity) || 1,
                unit_price_pre_tax: Number(invForm.unit_price_pre_tax) || 0,
                gst_rate_percent: Number(invForm.gst_rate_percent) || 0,
              },
            ],
          }).then(() => load()),
      });
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>Billing</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>Create invoice (single line)</h2>
        <p className="cc-muted" style={{ marginTop: -8 }}>
          POST <code>/billing/invoice</code> — requires billing permissions and factory billing where enforced.
        </p>
        <form onSubmit={createInvoice} style={{ display: "grid", gap: 8, maxWidth: 520 }}>
          <input
            className="cc-input"
            value={invForm.description}
            onChange={(e) => setInvForm((f) => ({ ...f, description: e.target.value }))}
            placeholder="Description"
          />
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              value={invForm.quantity}
              onChange={(e) => setInvForm((f) => ({ ...f, quantity: e.target.value }))}
              placeholder="Qty"
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              value={invForm.unit_price_pre_tax}
              onChange={(e) => setInvForm((f) => ({ ...f, unit_price_pre_tax: e.target.value }))}
              placeholder="Unit pre-tax"
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              value={invForm.gst_rate_percent}
              onChange={(e) => setInvForm((f) => ({ ...f, gst_rate_percent: e.target.value }))}
              placeholder="GST %"
            />
          </div>
          <button type="submit" className="cc-btn cc-btn-primary" style={{ width: 160 }}>
            Create invoice
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Record payment</h2>
        <form onSubmit={submitPayment} style={{ display: "grid", gap: 8, maxWidth: 480 }}>
          <input
            className="cc-input"
            placeholder="Invoice ID"
            value={pay.invoice_id}
            onChange={(e) => setPay((p) => ({ ...p, invoice_id: e.target.value }))}
            required
          />
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Amount INR"
              value={pay.amount_inr}
              onChange={(e) => setPay((p) => ({ ...p, amount_inr: e.target.value }))}
              required
            />
            <select
              className="cc-select"
              value={pay.method}
              onChange={(e) => setPay((p) => ({ ...p, method: e.target.value }))}
            >
              <option value="bank">bank</option>
              <option value="cash">cash</option>
              <option value="upi">upi</option>
            </select>
          </div>
          <input
            className="cc-input"
            placeholder="Reference (optional)"
            value={pay.reference}
            onChange={(e) => setPay((p) => ({ ...p, reference: e.target.value }))}
          />
          <button type="submit" className="cc-btn cc-btn-primary" style={{ width: 160 }}>
            Record payment
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Invoices</h2>
        <div className="cc-table-wrap">
          <table className="cc-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>No.</th>
                <th>Date</th>
                <th>Total</th>
                <th>Payment</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id}>
                  <td>{inv.id}</td>
                  <td>{inv.invoice_no || "—"}</td>
                  <td>{inv.invoice_date || "—"}</td>
                  <td>₹{Number(inv.grand_total_inr).toLocaleString("en-IN")}</td>
                  <td>
                    <span className="cc-pill">{inv.payment_status || "—"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
