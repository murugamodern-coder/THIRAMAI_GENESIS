import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import {
  createStructuredInvoice,
  fetchBillingBills,
  fetchInvoices,
  openCashBillPrint,
  openStructuredInvoicePrint,
  postSimpleCashBill,
  recordPayment,
} from "../../api/commandCenterApi.js";
import { orgUsesGst } from "../../business/orgMeta.js";

export default function BusinessBillingPage() {
  const { orgId } = useOutletContext();
  const gst = orgUsesGst(orgId);
  const [invoices, setInvoices] = useState([]);
  const [bills, setBills] = useState([]);
  const [err, setErr] = useState(null);
  const [supply, setSupply] = useState("intra");
  const [invForm, setInvForm] = useState({
    description: "Item",
    quantity: "1",
    unit_price_pre_tax: "100",
    gst_rate_percent: "18",
    hsn_code: "",
  });
  const [simple, setSimple] = useState({ description: "Bricks", quantity: "1000", unit_price_inr: "8500" });
  const [pay, setPay] = useState({ invoice_id: "", amount_inr: "", method: "cash", reference: "" });

  const load = useCallback(async () => {
    setErr(null);
    try {
      if (gst) {
        const out = await fetchInvoices(120);
        setInvoices(out?.invoices || []);
      }
      const b = await fetchBillingBills(80);
      setBills(b?.bills || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
    }
  }, [gst]);

  useEffect(() => {
    load();
  }, [load]);

  async function createInvoice(e) {
    e.preventDefault();
    setErr(null);
    try {
      await createStructuredInvoice({
        invoice_no: "",
        invoice_date: "",
        lines: [
          {
            description: invForm.description.trim(),
            quantity: Number(invForm.quantity) || 1,
            unit_price_pre_tax: Number(invForm.unit_price_pre_tax) || 0,
            gst_rate_percent: Number(invForm.gst_rate_percent) || 0,
            hsn_code: invForm.hsn_code.trim() || null,
          },
        ],
      });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Invoice failed");
    }
  }

  async function createSimple(e) {
    e.preventDefault();
    setErr(null);
    try {
      await postSimpleCashBill({
        lines: [
          {
            description: simple.description.trim(),
            quantity: Number(simple.quantity) || 1,
            unit_price_inr: Number(simple.unit_price_inr) || 0,
          },
        ],
      });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Bill failed");
    }
  }

  async function submitPay(e) {
    e.preventDefault();
    setErr(null);
    try {
      await recordPayment({
        invoice_id: Number(pay.invoice_id),
        amount_inr: Number(pay.amount_inr),
        method: pay.method,
        reference: pay.reference || null,
      });
      setPay({ invoice_id: "", amount_inr: "", method: "cash", reference: "" });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Payment failed");
    }
  }

  return (
    <div>
      <h1 className="biz-page-title">Billing</h1>
      {err && <p className="cc-error">{err}</p>}

      {gst && (
        <div className="cc-card">
          <h2>GST invoice</h2>
          <p className="cc-muted" style={{ fontSize: 12 }}>
            Print view splits CGST+SGST (local) or IGST (inter-state). Choose supply below before opening
            print.
          </p>
          <form onSubmit={createInvoice} style={{ display: "grid", gap: 8 }}>
            <input
              className="cc-input"
              value={invForm.description}
              onChange={(e) => setInvForm((f) => ({ ...f, description: e.target.value }))}
            />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input
                className="cc-input"
                type="number"
                step="any"
                placeholder="Qty"
                value={invForm.quantity}
                onChange={(e) => setInvForm((f) => ({ ...f, quantity: e.target.value }))}
              />
              <input
                className="cc-input"
                type="number"
                step="any"
                placeholder="Pre-tax rate"
                value={invForm.unit_price_pre_tax}
                onChange={(e) => setInvForm((f) => ({ ...f, unit_price_pre_tax: e.target.value }))}
              />
              <input
                className="cc-input"
                type="number"
                step="any"
                placeholder="GST %"
                value={invForm.gst_rate_percent}
                onChange={(e) => setInvForm((f) => ({ ...f, gst_rate_percent: e.target.value }))}
              />
              <input
                className="cc-input"
                placeholder="HSN"
                value={invForm.hsn_code}
                onChange={(e) => setInvForm((f) => ({ ...f, hsn_code: e.target.value }))}
              />
            </div>
            <button type="submit" className="cc-btn cc-btn-primary">
              Post invoice
            </button>
          </form>

          <div style={{ marginTop: 12 }}>
            <label className="cc-muted" style={{ fontSize: 13 }}>
              Print supply:{" "}
              <select className="cc-select" value={supply} onChange={(e) => setSupply(e.target.value)}>
                <option value="intra">Local (CGST + SGST)</option>
                <option value="inter">Inter-state (IGST)</option>
              </select>
            </label>
          </div>

          <h3 style={{ marginTop: 16 }}>Invoices</h3>
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13 }}>
            {invoices.slice(0, 25).map((inv) => (
              <li key={inv.id} style={{ marginBottom: 8 }}>
                #{inv.id} {inv.invoice_no} — ₹{inv.grand_total_inr}{" "}
                <span className="cc-muted">({inv.payment_status})</span>{" "}
                <button
                  type="button"
                  className="cc-btn cc-btn-secondary"
                  style={{ marginLeft: 8, padding: "4px 10px", fontSize: 12 }}
                  onClick={() => openStructuredInvoicePrint(inv.id, supply)}
                >
                  Print / PDF
                </button>
              </li>
            ))}
          </ul>

          <h3 style={{ marginTop: 16 }}>Record payment</h3>
          <form onSubmit={submitPay} style={{ display: "grid", gap: 8, maxWidth: 400 }}>
            <input
              className="cc-input"
              placeholder="Invoice id"
              value={pay.invoice_id}
              onChange={(e) => setPay((p) => ({ ...p, invoice_id: e.target.value }))}
              required
            />
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="cc-input"
                type="number"
                step="any"
                placeholder="Amount ₹"
                value={pay.amount_inr}
                onChange={(e) => setPay((p) => ({ ...p, amount_inr: e.target.value }))}
                required
              />
              <select
                className="cc-select"
                value={pay.method}
                onChange={(e) => setPay((p) => ({ ...p, method: e.target.value }))}
              >
                <option value="cash">cash</option>
                <option value="bank">bank</option>
                <option value="upi">upi</option>
              </select>
            </div>
            <input
              className="cc-input"
              placeholder="Reference"
              value={pay.reference}
              onChange={(e) => setPay((p) => ({ ...p, reference: e.target.value }))}
            />
            <button type="submit" className="cc-btn cc-btn-primary">
              Save payment
            </button>
          </form>
        </div>
      )}

      {!gst && (
        <div className="cc-card">
          <h2>Simple bill (no GST)</h2>
          <form onSubmit={createSimple} style={{ display: "grid", gap: 8 }}>
            <input
              className="cc-input"
              value={simple.description}
              onChange={(e) => setSimple((s) => ({ ...s, description: e.target.value }))}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="cc-input"
                type="number"
                step="any"
                placeholder="Qty"
                value={simple.quantity}
                onChange={(e) => setSimple((s) => ({ ...s, quantity: e.target.value }))}
              />
              <input
                className="cc-input"
                type="number"
                step="any"
                placeholder="₹ incl. (per unit)"
                value={simple.unit_price_inr}
                onChange={(e) => setSimple((s) => ({ ...s, unit_price_inr: e.target.value }))}
              />
            </div>
            <button type="submit" className="cc-btn cc-btn-primary">
              Post bill
            </button>
          </form>
        </div>
      )}

      <div className="cc-card">
        <h2>Cash bills (recent)</h2>
        <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13 }}>
          {bills.slice(0, 20).map((b) => (
            <li key={b.id} style={{ marginBottom: 8 }}>
              Bill #{b.id} — ₹{b.total_amount_inr}{" "}
              <button
                type="button"
                className="cc-btn cc-btn-secondary"
                style={{ marginLeft: 8, padding: "4px 10px", fontSize: 12 }}
                onClick={() => openCashBillPrint(b.id)}
              >
                Print
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
