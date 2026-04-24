import { useMemo } from "react";

function safeJson(obj) {
  try {
    return JSON.stringify(obj ?? {}, null, 2);
  } catch {
    return String(obj ?? "");
  }
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();
  if (s === "success") return "text-emerald-300";
  if (s === "partial") return "text-amber-300";
  if (s === "failed") return "text-red-300";
  return "text-slate-300";
}

/**
 * Single unified block: plan → execution result → status (POST /brain/execute shape).
 */
export default function BrainResponseBlock({ brain, className = "" }) {
  const plan = useMemo(() => (Array.isArray(brain?.plan) ? brain.plan : []), [brain]);
  const result = brain?.result;
  const stepsOut = useMemo(() => (Array.isArray(result?.steps) ? result.steps : []), [result]);
  const stopped = result && typeof result === "object" ? result.stopped : null;

  return (
    <div className={`space-y-3 rounded-xl border border-slate-700/80 bg-slate-950/50 p-4 ${className}`.trim()}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Brain</span>
        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-200">
          intent: <strong className="text-blue-300">{String(brain?.intent || "—")}</strong>
        </span>
        <span className={`rounded-full bg-slate-800 px-2 py-0.5 text-xs font-medium ${statusClass(brain?.status)}`}>
          {String(brain?.status || "unknown")}
        </span>
        {result?.run_id != null ? (
          <span className="text-[11px] text-slate-500">run #{String(result.run_id)}</span>
        ) : null}
      </div>

      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Plan</h4>
        {plan.length === 0 ? (
          <p className="text-sm text-slate-500">No plan steps.</p>
        ) : (
          <ul className="space-y-1.5 text-sm text-slate-200">
            {plan.map((row, i) => {
              const o = row?.step_order ?? i;
              const sk = String(row?.step_kind || "—");
              const ph = String(row?.phase || "");
              const safety = row?.safety && typeof row.safety === "object" ? row.safety : null;
              const tier = safety?.approval_tier ? String(safety.approval_tier) : "";
              const score = safety?.risk_score != null ? String(safety.risk_score) : "";
              return (
                <li key={`p_${o}_${i}`} className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
                  <div className="font-medium text-slate-100">
                    <span className="text-slate-500">#{o}</span> {ph ? `${ph} · ` : ""}
                    {sk}
                  </div>
                  {tier || score ? (
                    <div className="mt-1 text-xs text-slate-500">
                      {tier ? `tier ${tier}` : ""}
                      {tier && score ? " · " : ""}
                      {score ? `risk ${score}` : ""}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Execution</h4>
        {stopped ? (
          <div className="rounded-lg border border-amber-600/40 bg-amber-950/30 px-3 py-2 text-sm text-amber-100">
            <div className="font-medium">Paused — confirmation</div>
            <div className="mt-1 text-xs text-amber-200/90">{String(stopped.reason || "")}</div>
            {stopped.step_kind ? (
              <div className="mt-1 text-xs text-slate-400">
                step: {String(stopped.step_kind)} (order {String(stopped.step_order ?? "—")})
              </div>
            ) : null}
          </div>
        ) : null}
        {result?.blocked ? (
          <div className="rounded-lg border border-red-700/50 bg-red-950/30 px-3 py-2 text-sm text-red-100">
            Blocked: {String(result.reason || "governance or safety")}
          </div>
        ) : null}
        {stepsOut.length > 0 ? (
          <ul className="space-y-1.5">
            {stepsOut.map((s, i) => {
              const st = String(s?.status || s?.outcome || "").toLowerCase();
              const ok = s?.ok !== false && !["failed", "error"].includes(st);
              return (
                <li
                  key={`e_${s?.step_order ?? i}`}
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
                    ok ? "border-slate-800 bg-slate-900/40 text-slate-200" : "border-red-900/50 bg-red-950/20 text-red-100"
                  }`}
                >
                  <span className="mt-0.5 text-slate-500">#{String(s?.step_order ?? i)}</span>
                  <div>
                    <div className="font-medium">{String(s?.step_kind || "step")}</div>
                    {s?.skipped ? <div className="text-xs text-slate-500">skipped</div> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : !stopped && !result?.blocked ? (
          <pre className="max-h-40 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-300">{safeJson(result)}</pre>
        ) : null}
      </section>

      <details className="rounded-lg border border-slate-800 bg-slate-900/30">
        <summary className="cursor-pointer px-3 py-2 text-xs text-slate-500">Raw response</summary>
        <pre className="max-h-48 overflow-auto border-t border-slate-800 p-3 text-xs text-slate-400">{safeJson(brain)}</pre>
      </details>
    </div>
  );
}
