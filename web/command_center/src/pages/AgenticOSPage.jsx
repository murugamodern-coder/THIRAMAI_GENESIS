import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import api from "../api/client.js";
import {
  fetchCodeAgentTask,
  fetchCodeAgentTasks,
  fetchWebsitesList,
  postCodeAgentDeploy,
  postCodeAgentGenerate,
  postCodeAgentTest,
  postSelfHealAnalyze,
  postSelfHealApply,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

const GEN_STEPS = ["🤔 Analyzing task...", "✍️ Writing code...", "🔍 Checking syntax...", "✅ Ready!"];

function CardSection({ title, subtitle, children }) {
  return (
    <section className="cc-card" style={{ marginBottom: 20 }}>
      <h2 className="cc-section-title" style={{ marginTop: 0 }}>
        {title}
      </h2>
      {subtitle ? (
        <p className="cc-muted" style={{ marginTop: 0, marginBottom: 14 }}>
          {subtitle}
        </p>
      ) : null}
      {children}
    </section>
  );
}

export default function AgenticOSPage() {
  const [task, setTask] = useState("");
  const [language, setLanguage] = useState("python");
  const [context, setContext] = useState("FastAPI backend");

  const [genBusy, setGenBusy] = useState(false);
  const [genStep, setGenStep] = useState(0);
  const genTimerRef = useRef(null);
  const [lastGen, setLastGen] = useState(null);

  const [testBusy, setTestBusy] = useState(false);
  const [testOut, setTestOut] = useState(null);

  const [deployPath, setDeployPath] = useState("app/generated/thiramai_agent_export.py");
  const [deployToken, setDeployToken] = useState("");
  const [deployBusy, setDeployBusy] = useState(false);

  const [healLog, setHealLog] = useState("");
  const [healProposal, setHealProposal] = useState(null);
  const [healBusy, setHealBusy] = useState(false);
  const [applyBusy, setApplyBusy] = useState(false);

  const [websites, setWebsites] = useState([]);
  const [sitesBusy, setSitesBusy] = useState(true);

  const [tasks, setTasks] = useState([]);
  const [tasksBusy, setTasksBusy] = useState(true);
  const [expandedTaskId, setExpandedTaskId] = useState(null);
  const [expandedDetail, setExpandedDetail] = useState(null);

  const loadSites = useCallback(async () => {
    setSitesBusy(true);
    try {
      const data = await fetchWebsitesList();
      const list = Array.isArray(data?.websites) ? data.websites : [];
      setWebsites(list);
    } catch {
      setWebsites([]);
    } finally {
      setSitesBusy(false);
    }
  }, []);

  const loadTasks = useCallback(async () => {
    setTasksBusy(true);
    try {
      const data = await fetchCodeAgentTasks();
      setTasks(Array.isArray(data?.tasks) ? data.tasks : []);
    } catch {
      setTasks([]);
    } finally {
      setTasksBusy(false);
    }
  }, []);

  useEffect(() => {
    loadSites();
    loadTasks();
  }, [loadSites, loadTasks]);

  useEffect(() => {
    const t = window.setInterval(() => {
      loadTasks().catch(() => {});
    }, 30000);
    return () => window.clearInterval(t);
  }, [loadTasks]);

  useEffect(() => {
    return () => {
      if (genTimerRef.current) window.clearInterval(genTimerRef.current);
    };
  }, []);

  const langOptions = useMemo(
    () => [
      ["python", "Python"],
      ["javascript", "JavaScript"],
      ["typescript", "TypeScript"],
      ["react", "React (JSX)"],
    ],
    [],
  );

  async function runGenerate() {
    const t = task.trim();
    if (!t || genBusy) return;
    setGenBusy(true);
    setLastGen(null);
    setTestOut(null);
    setGenStep(0);
    if (genTimerRef.current) window.clearInterval(genTimerRef.current);
    genTimerRef.current = window.setInterval(() => {
      setGenStep((s) => Math.min(s + 1, GEN_STEPS.length - 1));
    }, 550);

    try {
      const data = await postCodeAgentGenerate({
        task: t,
        language,
        context: context.trim(),
      });
      setLastGen(data);
      setGenStep(GEN_STEPS.length - 1);
      showToastDedup({ type: "success", message: data?.syntax_ok ? "Code generated" : "Generated (syntax issues)" });
      await loadTasks();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : e?.message || "Generate failed" });
      setGenStep(0);
    } finally {
      setGenBusy(false);
      if (genTimerRef.current) {
        window.clearInterval(genTimerRef.current);
        genTimerRef.current = null;
      }
    }
  }

  async function runTest() {
    const id = lastGen?.task_id;
    if (!id || testBusy) return;
    setTestBusy(true);
    setTestOut(null);
    try {
      const data = await postCodeAgentTest(id);
      setTestOut(data);
      await loadTasks();
      showToastDedup({ type: data?.ok ? "success" : "warning", message: data?.ok ? "Run finished" : "Run reported errors" });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.response?.data?.detail || e?.message || "Test failed" });
    } finally {
      setTestBusy(false);
    }
  }

  async function runDeploy() {
    const id = lastGen?.task_id;
    if (!id || deployBusy) return;
    setDeployBusy(true);
    try {
      await postCodeAgentDeploy({
        task_id: id,
        target_path: deployPath.trim(),
        confirmation_token: deployToken.trim(),
      });
      showToastDedup({ type: "success", message: "Deployed & commit attempted" });
      await loadTasks();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : e?.message || "Deploy failed" });
    } finally {
      setDeployBusy(false);
    }
  }

  async function runHeal() {
    const log = healLog.trim();
    if (!log || healBusy) return;
    setHealBusy(true);
    setHealProposal(null);
    try {
      const data = await postSelfHealAnalyze(log);
      setHealProposal(data);
      showToastDedup({ type: "success", message: "Proposal ready — review before apply." });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.response?.data?.detail || e?.message || "Analyze failed" });
    } finally {
      setHealBusy(false);
    }
  }

  async function runHealApply() {
    const cmd = healProposal?.command;
    if (!cmd || applyBusy) return;
    setApplyBusy(true);
    try {
      await postSelfHealApply({
        confirmation_token: deployToken.trim(),
        command: cmd,
      });
      showToastDedup({ type: "success", message: "Apply command executed (check stderr in response)." });
      setHealProposal(null);
      setHealLog("");
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : e?.message || "Apply failed" });
    } finally {
      setApplyBusy(false);
    }
  }

  async function toggleExpand(id) {
    if (expandedTaskId === id) {
      setExpandedTaskId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedTaskId(id);
    try {
      const data = await fetchCodeAgentTask(id);
      setExpandedDetail(data?.task ?? null);
    } catch {
      setExpandedDetail(null);
    }
  }

  function fillChip(text) {
    setTask(text);
  }

  const codePreview = lastGen?.preview || lastGen?.code || "";

  return (
    <div className="agentic-os-page" style={{ maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ marginBottom: 24 }}>
        <h1 className="cc-page-title">Agentic OS</h1>
        <p className="cc-muted">Thiramai-native agents: code generation, self-heal, and your websites — no external IDEs required.</p>
      </div>

      {/* Section 1 — Code Agent */}
      <CardSection
        title="🤖 THIRAMAI CODE AGENT"
        subtitle="Describe what you want to build. Generation uses Groq (llama-3.3-70b-versatile), syntax check, and optional test/deploy."
      >
        <label className="cc-muted" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
          Describe what you want to build
        </label>
        <textarea
          className="cc-input"
          rows={4}
          style={{ width: "100%", resize: "vertical", fontFamily: "inherit" }}
          placeholder='e.g. "Create a GST invoice PDF helper"'
          value={task}
          onChange={(e) => setTask(e.target.value)}
        />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 12, alignItems: "center" }}>
          <label className="cc-muted" style={{ fontSize: 13 }}>
            Language
            <select className="cc-input" style={{ marginLeft: 8, minWidth: 140 }} value={language} onChange={(e) => setLanguage(e.target.value)}>
              {langOptions.map(([v, lab]) => (
                <option key={v} value={v}>
                  {lab}
                </option>
              ))}
            </select>
          </label>
          <label className="cc-muted" style={{ fontSize: 13, flex: "1 1 200px" }}>
            Context
            <input className="cc-input" style={{ width: "100%", marginTop: 4 }} value={context} onChange={(e) => setContext(e.target.value)} />
          </label>
        </div>
        <div style={{ marginTop: 14 }}>
          <button type="button" className="cc-btn cc-btn-primary" disabled={genBusy || !task.trim()} onClick={() => runGenerate()}>
            {genBusy ? "Working…" : "⚡ Generate Code"}
          </button>
          {genBusy ? (
            <span className="cc-muted" style={{ marginLeft: 12, fontSize: 14 }}>
              {GEN_STEPS[genStep]}
            </span>
          ) : null}
        </div>

        {lastGen ? (
          <div style={{ marginTop: 20 }}>
            <div className="cc-muted" style={{ fontSize: 12, marginBottom: 8 }}>
              OUTPUT {lastGen.syntax_ok ? <span style={{ color: "#10b981" }}>✅ Syntax OK</span> : <span style={{ color: "#f59e0b" }}>⚠ Syntax issues</span>}
            </div>
            <pre
              style={{
                margin: 0,
                padding: 14,
                borderRadius: 12,
                background: "var(--cc-surface-2, rgba(0,0,0,0.04))",
                border: "1px solid var(--cc-border, #e5e7eb)",
                fontSize: 12,
                overflow: "auto",
                maxHeight: 360,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {codePreview || "—"}
            </pre>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12, alignItems: "center" }}>
              <button type="button" className="cc-btn cc-btn-ghost" disabled={testBusy || !lastGen.task_id} onClick={() => runTest()}>
                {testBusy ? "Running…" : "▶ Test"}
              </button>
              <span className="cc-muted" style={{ fontSize: 12 }}>
                Deploy needs <code>THIRAMAI_CODE_AGENT_DEPLOY_TOKEN</code> (paste below).
              </span>
            </div>
            <div style={{ display: "grid", gap: 8, marginTop: 12, maxWidth: 520 }}>
              <input className="cc-input" placeholder="target_path (repo-relative)" value={deployPath} onChange={(e) => setDeployPath(e.target.value)} />
              <input
                className="cc-input"
                type="password"
                autoComplete="off"
                placeholder="Deploy / apply confirmation token"
                value={deployToken}
                onChange={(e) => setDeployToken(e.target.value)}
              />
              <button type="button" className="cc-btn cc-btn-primary" disabled={deployBusy || !lastGen.task_id} onClick={() => runDeploy()}>
                {deployBusy ? "Deploying…" : "🚀 Deploy"}
              </button>
            </div>
            {testOut ? (
              <pre
                style={{
                  marginTop: 12,
                  padding: 12,
                  borderRadius: 10,
                  fontSize: 12,
                  background: testOut.ok ? "rgba(16,185,129,0.08)" : "rgba(239,68,68,0.08)",
                  maxHeight: 200,
                  overflow: "auto",
                }}
              >
                {testOut.output || testOut.errors || JSON.stringify(testOut, null, 2)}
              </pre>
            ) : null}
          </div>
        ) : null}
      </CardSection>

      {/* Section 2 — Self-heal */}
      <CardSection title="🔧 SELF-HEAL" subtitle="Paste a traceback or error line; Groq proposes a fix (approval required for pip install).">
        <textarea
          className="cc-input"
          rows={5}
          style={{ width: "100%", resize: "vertical" }}
          placeholder={'ModuleNotFoundError: No module named \'fpdf\''}
          value={healLog}
          onChange={(e) => setHealLog(e.target.value)}
        />
        <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button type="button" className="cc-btn cc-btn-primary" disabled={healBusy || !healLog.trim()} onClick={() => runHeal()}>
            {healBusy ? "Analyzing…" : "🔍 Analyze & Fix"}
          </button>
        </div>
        {healProposal ? (
          <div className="cc-card" style={{ marginTop: 14, padding: 14 }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Proposed fix</div>
            <p style={{ margin: "0 0 8px", fontSize: 14 }}>{healProposal.explanation || healProposal.fix_type}</p>
            {healProposal.command ? (
              <pre style={{ margin: 0, padding: 10, borderRadius: 8, background: "var(--cc-surface-2, #f4f4f5)", fontSize: 13 }}>{healProposal.command}</pre>
            ) : null}
            <div style={{ marginTop: 12, display: "flex", gap: 10 }}>
              <button type="button" className="cc-btn cc-btn-primary" disabled={applyBusy || !healProposal.command} onClick={() => runHealApply()}>
                {applyBusy ? "Running…" : "✅ Approve & Run"}
              </button>
              <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setHealProposal(null)}>
                ❌ Reject
              </button>
            </div>
          </div>
        ) : null}
      </CardSection>

      {/* Section 3 — Websites */}
      <CardSection title="Your websites" subtitle="From the website builder (per organization).">
        {sitesBusy ? (
          <div className="ui-skeleton" style={{ height: 80, borderRadius: 12 }} />
        ) : websites.length === 0 ? (
          <p className="cc-muted">No website metadata yet — create one from the builder.</p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {websites.map((w) => (
              <div
                key={w.organization_id}
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 10,
                  padding: "12px 14px",
                  borderRadius: 12,
                  border: "1px solid var(--cc-border, #e5e7eb)",
                }}
              >
                <div>
                  <strong>{w.name}</strong>
                  <span className="cc-muted" style={{ marginLeft: 8, fontSize: 12 }}>
                    Org #{w.organization_id}
                  </span>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    Status: <strong>{w.status}</strong>
                    {w.slug ? (
                      <span className="cc-muted">
                        {" "}
                        · slug {w.slug}
                      </span>
                    ) : null}
                  </div>
                  {w.url ? (
                    <a href={w.url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
                      {w.url}
                    </a>
                  ) : (
                    <span className="cc-muted" style={{ fontSize: 12 }}>
                      No public URL yet
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <Link className="cc-btn cc-btn-ghost" to={`/business/${w.organization_id}/dashboard`}>
                    Edit
                  </Link>
                  <button
                    type="button"
                    className="cc-btn cc-btn-ghost"
                    onClick={async () => {
                      try {
                        await api.post("/website-builder/deploy", { organization_id: w.organization_id });
                        showToastDedup({ type: "success", message: "Deploy triggered" });
                        loadSites();
                      } catch (e) {
                        showToastDedup({ type: "error", message: e?.response?.data?.detail || "Deploy failed" });
                      }
                    }}
                  >
                    Deploy
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <Link className="cc-btn cc-btn-primary" style={{ marginTop: 14, display: "inline-block" }} to="/dashboard">
          + Create new website
        </Link>
      </CardSection>

      {/* Section 4 — Tasks */}
      <CardSection title="Active agent tasks" subtitle="Recent code generations (stored in-process on the API).">
        {tasksBusy ? (
          <div className="ui-skeleton" style={{ height: 100, borderRadius: 12 }} />
        ) : tasks.length === 0 ? (
          <p className="cc-muted">No tasks yet.</p>
        ) : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 8 }}>
            {tasks.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => toggleExpand(t.id)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "12px 14px",
                    borderRadius: 12,
                    border: "1px solid var(--cc-border, #e5e7eb)",
                    background: "var(--cc-card-bg, transparent)",
                    cursor: "pointer",
                  }}
                >
                  <strong>{t.task?.slice(0, 120) || t.id}</strong>
                  <span className="cc-muted" style={{ fontSize: 12, marginLeft: 8 }}>
                    {t.status} · {t.created_at ? new Date(t.created_at).toLocaleString() : ""}
                  </span>
                </button>
                {expandedTaskId === t.id && expandedDetail ? (
                  <div style={{ padding: "12px 14px", fontSize: 13 }}>
                    <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 240, overflow: "auto" }}>
                      {(expandedDetail.code || "").slice(0, 12000)}
                    </pre>
                    {expandedDetail.last_test_output ? (
                      <div style={{ marginTop: 10 }}>
                        <div className="cc-muted" style={{ fontSize: 11 }}>
                          Last test
                        </div>
                        <pre style={{ fontSize: 12, maxHeight: 160, overflow: "auto" }}>{expandedDetail.last_test_output}</pre>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardSection>

      {/* Section 5 — Automation */}
      <CardSection
        title="Automation rules"
        subtitle="Scheduler jobs running on the API host (see workers / services.scheduler)."
      >
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 14, lineHeight: 1.7 }}>
          <li>Every morning (IST) → Morning brief & equity checks where enabled</li>
          <li>Every few minutes → Stock alert monitor tick (when workers run)</li>
          <li>Sovereign / alert schedulers → control-plane jobs from env</li>
        </ul>
        <button type="button" className="cc-btn cc-btn-ghost" disabled title="Coming soon">
          + Add rule
        </button>
      </CardSection>

      {/* Section 6 — Chips */}
      <CardSection title="Quick actions" subtitle="Prefill the code agent prompt.">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {[
            ["📝 Write a Python script", "Write a Python CLI script that reads CSV and prints summary stats"],
            ["🌐 Create a landing page", "Create a React functional component landing page with hero and CTA"],
            ["🔧 Fix a bug", "Write a Python function with try/except that safely parses JSON from a file"],
            ["📊 Analyze my data", "Write Python code using pandas to load a CSV and show column dtypes"],
          ].map(([label, text]) => (
            <button key={label} type="button" className="cc-btn cc-btn-ghost" onClick={() => fillChip(text)}>
              {label}
            </button>
          ))}
        </div>
      </CardSection>
    </div>
  );
}
