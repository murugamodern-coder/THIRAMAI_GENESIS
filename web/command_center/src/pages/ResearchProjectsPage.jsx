import { useCallback, useEffect, useState } from "react";

import {
  fetchResearchProjectResults,
  fetchResearchProjects,
  postResearchProject,
  postRunResearchProject,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

export default function ResearchProjectsPage() {
  const [rows, setRows] = useState([]);
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("general");
  const [selectedId, setSelectedId] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [runningId, setRunningId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const out = await fetchResearchProjects(100);
      setRows(Array.isArray(out?.items) ? out.items : []);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load projects" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 8000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function createProject() {
    if (!title.trim()) return;
    try {
      const out = await postResearchProject({ title: title.trim(), domain });
      setTitle("");
      await load();
      if (out?.project_id) setSelectedId(out.project_id);
      showToastDedup({ type: "success", message: "Research project created" });
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Create failed" });
    }
  }

  async function runProject(projectId) {
    setRunningId(projectId);
    try {
      await postRunResearchProject(projectId, 4);
      await load();
      showToastDedup({ type: "success", message: "Overnight research started" });
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Run failed" });
    } finally {
      setRunningId(null);
    }
  }

  async function viewResults(projectId) {
    setSelectedId(projectId);
    try {
      const out = await fetchResearchProjectResults(projectId);
      setResult(out?.outputs || null);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load output" });
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Research Projects</h1>
        <p className="mt-1 text-sm text-slate-400">Overnight autonomous research workspace with final actionable output.</p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="grid gap-2 md:grid-cols-4">
          <input
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:col-span-2"
            placeholder="Research objective..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <input
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="Domain"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
          />
          <button type="button" className="rounded-md border border-emerald-600 px-3 py-2 text-sm text-emerald-200" onClick={createProject}>
            Create Project
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Project List</h2>
          {loading ? <div className="text-sm text-slate-400">Loading...</div> : null}
          <div className="space-y-2">
            {rows.map((r) => (
              <div key={r.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-slate-100">{r.title}</div>
                    <div className="mt-1 text-xs text-slate-400">
                      {r.domain} | status: {r.status}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded-md border border-blue-600 px-2 py-1 text-xs text-blue-200 disabled:opacity-60"
                      onClick={() => runProject(r.id)}
                      disabled={runningId === r.id || r.status === "running"}
                    >
                      Run
                    </button>
                    <button
                      type="button"
                      className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200"
                      onClick={() => viewResults(r.id)}
                    >
                      View Output
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {!rows.length && !loading ? <div className="text-sm text-slate-400">No projects yet.</div> : null}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Final Output</h2>
          {!selectedId ? <div className="text-sm text-slate-400">Select a project to view output.</div> : null}
          {selectedId && !result ? <div className="text-sm text-slate-400">No final output yet (project may still be running).</div> : null}
          {result ? (
            <div className="space-y-2 text-sm text-slate-200">
              <div className="rounded-md border border-slate-700 bg-slate-950/40 p-2">
                <div className="text-xs text-slate-400">Problem Understanding</div>
                <div>{result?.problem_understanding?.scope || "n/a"}</div>
              </div>
              <div className="rounded-md border border-slate-700 bg-slate-950/40 p-2">
                <div className="text-xs text-slate-400">Best Solution</div>
                <div>{result?.best_solution?.title || "n/a"}</div>
              </div>
              <div className="rounded-md border border-slate-700 bg-slate-950/40 p-2">
                <div className="text-xs text-slate-400">Risks</div>
                <div>{Array.isArray(result?.risks) ? result.risks.join(" | ") : "n/a"}</div>
              </div>
              <div className="rounded-md border border-slate-700 bg-slate-950/40 p-2">
                <div className="text-xs text-slate-400">Next Actions</div>
                <div>{Array.isArray(result?.next_actions) ? result.next_actions.join(" | ") : "n/a"}</div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
