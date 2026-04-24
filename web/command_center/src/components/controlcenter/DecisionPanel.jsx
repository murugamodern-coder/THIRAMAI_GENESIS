function UrgencyTag({ value }) {
  const v = String(value || "medium").toLowerCase();
  const cls =
    v === "high"
      ? "border-red-500/40 bg-red-500/10 text-red-200"
      : v === "low"
        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
        : "border-amber-500/40 bg-amber-500/10 text-amber-200";
  return <span className={`rounded-md border px-2 py-0.5 text-xs ${cls}`}>{v}</span>;
}

export default function DecisionPanel({ decisions = [], onExecute, onSimulate, onIgnore }) {
  const items = decisions.length
    ? decisions.slice(0, 3)
    : [
        {
          id: "d_fallback_1",
          title: "Increase high-confidence mission budget by 5%",
          impact: "Potential +2.1% weekly margin if conversion holds.",
          urgency: "medium",
        },
      ];

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">Decision Panel</h2>
        <span className="text-xs text-slate-500">Top 3 prioritized decisions</span>
      </div>
      <div className="space-y-2">
        {items.map((d) => (
          <article key={d.id} className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-100">{d.title}</h3>
              <UrgencyTag value={d.urgency} />
            </div>
            <p className="mt-2 text-xs text-slate-300">{d.impact}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500" onClick={() => onExecute?.(d)}>
                Execute
              </button>
              <button type="button" className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800" onClick={() => onSimulate?.(d)}>
                Simulate
              </button>
              <button type="button" className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-900" onClick={() => onIgnore?.(d)}>
                Ignore
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
