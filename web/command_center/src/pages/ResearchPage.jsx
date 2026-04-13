import { useCallback, useState } from "react";

import {
  getResearchDprQuery,
  postResearchCompetitors,
  postResearchDpr,
  postResearchMarket,
  postResearchSchemes,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

function Card({ title, children }) {
  return (
    <section className="cc-card" style={{ marginBottom: 20 }}>
      <h2 className="cc-today-card-title">{title}</h2>
      {children}
    </section>
  );
}

function downloadPdfBase64(b64, filename) {
  if (!b64) return;
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ResearchPage() {
  const [loading, setLoading] = useState(false);
  const [marketQuery, setMarketQuery] = useState("groundnut oil cold pressed Tamil Nadu");
  const [marketOut, setMarketOut] = useState(null);
  const [sector, setSector] = useState("food processing");
  const [state, setState] = useState("TN");
  const [schemesOut, setSchemesOut] = useState(null);
  const [dprBiz, setDprBiz] = useState("small scale HDPE pipe extrusion");
  const [dprCap, setDprCap] = useState("300 MT/year");
  const [dprLoc, setDprLoc] = useState("Coimbatore district");
  const [dprOut, setDprOut] = useState(null);
  const [compBiz, setCompBiz] = useState("organic grocery retail");
  const [compLoc, setCompLoc] = useState("Chennai");
  const [compOut, setCompOut] = useState(null);

  const runMarket = useCallback(async () => {
    const q = marketQuery.trim();
    if (!q) return;
    setLoading(true);
    setMarketOut(null);
    try {
      const data = await postResearchMarket(q);
      setMarketOut(data);
      showToastDedup({ type: data?.ok ? "success" : "warning", message: data?.ok ? "Market research done" : "Check API keys" });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Failed" });
    } finally {
      setLoading(false);
    }
  }, [marketQuery]);

  const runSchemes = useCallback(async () => {
    const s = sector.trim();
    if (!s) return;
    setLoading(true);
    setSchemesOut(null);
    try {
      const data = await postResearchSchemes(s, state.trim() || "TN");
      setSchemesOut(data);
      showToastDedup({ type: "success", message: "Schemes search complete" });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Failed" });
    } finally {
      setLoading(false);
    }
  }, [sector, state]);

  const runDpr = useCallback(async () => {
    const b = dprBiz.trim();
    if (!b) return;
    setLoading(true);
    setDprOut(null);
    try {
      const data = await postResearchDpr({
        businessType: b,
        capacity: dprCap,
        location: dprLoc,
      });
      setDprOut(data);
      showToastDedup({ type: "success", message: "DPR generated" });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Failed" });
    } finally {
      setLoading(false);
    }
  }, [dprBiz, dprCap, dprLoc]);

  const downloadDprPdf = useCallback(async () => {
    const b = dprBiz.trim();
    if (!b) return;
    setLoading(true);
    try {
      const data = await getResearchDprQuery({
        businessType: b,
        capacity: dprCap,
        location: dprLoc,
        format: "json",
      });
      if (data?.pdf_base64) {
        downloadPdfBase64(data.pdf_base64, "thiramai-dpr.pdf");
        showToastDedup({ type: "success", message: "PDF downloaded" });
      } else {
        showToastDedup({ type: "warning", message: "No PDF in response (check fpdf / logs)" });
      }
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Failed" });
    } finally {
      setLoading(false);
    }
  }, [dprBiz, dprCap, dprLoc]);

  const runComp = useCallback(async () => {
    const b = compBiz.trim();
    if (!b) return;
    setLoading(true);
    setCompOut(null);
    try {
      const data = await postResearchCompetitors(b, compLoc);
      setCompOut(data);
      showToastDedup({ type: "success", message: "Competitor scan done" });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Failed" });
    } finally {
      setLoading(false);
    }
  }, [compBiz, compLoc]);

  const struct = marketOut?.structured;

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "16px 20px 48px" }}>
      <h1 style={{ fontSize: 26, marginBottom: 8 }}>Research engine</h1>
      <p className="cc-muted" style={{ marginBottom: 24 }}>
        Market intelligence, government schemes, DPR drafts, and competitor scans. Results are saved to your workspace
        (requires Tavily + Groq; Gemini optional via GOOGLE_API_KEY).
      </p>

      <Card title="Market research">
        <textarea
          className="cc-textarea"
          rows={3}
          value={marketQuery}
          onChange={(e) => setMarketQuery(e.target.value)}
          disabled={loading}
        />
        <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={runMarket} style={{ marginTop: 8 }}>
          {loading ? "Running…" : "Run research"}
        </button>
        {struct ? (
          <div style={{ marginTop: 16, fontSize: 14 }}>
            <p>
              <strong>Market size:</strong> {struct.market_size || "—"}
            </p>
            <p>
              <strong>Growth:</strong> {struct.growth_rate || "—"}
            </p>
            <p>
              <strong>Top players:</strong> {(struct.top_players || []).join(", ") || "—"}
            </p>
            <p>
              <strong>Price trends:</strong> {struct.price_trends || "—"}
            </p>
            <p>
              <strong>Demand:</strong> {struct.demand_forecast || "—"}
            </p>
            <p>
              <strong>Opportunities:</strong>
            </p>
            <ul>
              {(struct.opportunities || []).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
            {marketOut?.document_id ? (
              <p className="cc-muted" style={{ fontSize: 12 }}>
                Saved as document #{marketOut.document_id}
              </p>
            ) : null}
          </div>
        ) : null}
      </Card>

      <Card title="Government schemes">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input
            className="cc-textarea"
            style={{ minHeight: 40, flex: "1 1 200px" }}
            placeholder="Sector"
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            disabled={loading}
          />
          <input
            className="cc-textarea"
            style={{ minHeight: 40, width: 100 }}
            placeholder="State"
            value={state}
            onChange={(e) => setState(e.target.value)}
            disabled={loading}
          />
          <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={runSchemes}>
            Find schemes
          </button>
        </div>
        {Array.isArray(schemesOut?.schemes) && schemesOut.schemes.length > 0 ? (
          <ul style={{ marginTop: 16, paddingLeft: 18 }}>
            {schemesOut.schemes.map((s, i) => (
              <li key={i} style={{ marginBottom: 12 }}>
                <strong>{s.scheme_name || s.name || "Scheme"}</strong>
                <div className="cc-muted" style={{ fontSize: 13 }}>
                  {s.subsidy_amount ? `Subsidy: ${s.subsidy_amount} · ` : ""}
                  {s.deadline ? `Deadline: ${s.deadline}` : ""}
                </div>
                <div style={{ fontSize: 13 }}>{s.eligibility}</div>
                {s.application_url ? (
                  <a href={s.application_url} target="_blank" rel="noreferrer">
                    Link
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </Card>

      <Card title="DPR generator">
        <input
          className="cc-textarea"
          style={{ minHeight: 40, marginBottom: 8, width: "100%" }}
          placeholder="Business type"
          value={dprBiz}
          onChange={(e) => setDprBiz(e.target.value)}
          disabled={loading}
        />
        <input
          className="cc-textarea"
          style={{ minHeight: 40, marginBottom: 8, width: "100%" }}
          placeholder="Capacity"
          value={dprCap}
          onChange={(e) => setDprCap(e.target.value)}
          disabled={loading}
        />
        <input
          className="cc-textarea"
          style={{ minHeight: 40, marginBottom: 8, width: "100%" }}
          placeholder="Location"
          value={dprLoc}
          onChange={(e) => setDprLoc(e.target.value)}
          disabled={loading}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={runDpr}>
            Generate (preview JSON)
          </button>
          <button type="button" className="cc-btn cc-btn-secondary" disabled={loading} onClick={downloadDprPdf}>
            Download PDF
          </button>
        </div>
        {dprOut?.report ? (
          <details style={{ marginTop: 12 }}>
            <summary className="cc-muted" style={{ cursor: "pointer" }}>
              Structured sections
            </summary>
            <pre style={{ fontSize: 12, overflow: "auto", maxHeight: 320 }}>{JSON.stringify(dprOut.report, null, 2)}</pre>
          </details>
        ) : null}
      </Card>

      <Card title="Competitor analysis">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <input
            className="cc-textarea"
            style={{ minHeight: 40, flex: "1 1 200px" }}
            placeholder="Business type"
            value={compBiz}
            onChange={(e) => setCompBiz(e.target.value)}
            disabled={loading}
          />
          <input
            className="cc-textarea"
            style={{ minHeight: 40, flex: "1 1 160px" }}
            placeholder="Location"
            value={compLoc}
            onChange={(e) => setCompLoc(e.target.value)}
            disabled={loading}
          />
          <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={runComp}>
            Analyze
          </button>
        </div>
        {Array.isArray(compOut?.competitors) && compOut.competitors.length > 0 ? (
          <div style={{ marginTop: 16, display: "grid", gap: 12 }}>
            {compOut.competitors.map((c, i) => (
              <div key={i} className="cc-card" style={{ padding: 12 }}>
                <div style={{ fontWeight: 700 }}>{c.name || "Competitor"}</div>
                <div className="cc-muted" style={{ fontSize: 13 }}>
                  {c.location || ""} · {c.pricing || ""}
                </div>
                <p style={{ fontSize: 13, margin: "8px 0 0" }}>
                  <strong>Strengths:</strong> {c.strengths}
                </p>
                <p style={{ fontSize: 13 }}>
                  <strong>Weaknesses:</strong> {c.weaknesses}
                </p>
              </div>
            ))}
            {compOut.gaps?.length ? (
              <div>
                <strong>Gaps</strong>
                <ul>
                  {compOut.gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </Card>
    </div>
  );
}
