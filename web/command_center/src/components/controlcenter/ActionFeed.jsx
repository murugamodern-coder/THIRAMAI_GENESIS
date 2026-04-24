export default function ActionFeed({ safeMode, lastAction, lastKnown }) {
  const action =
    lastAction || lastKnown?.lastAction || {
      title: "Guardrail calibration completed",
      impact: "+1.4% margin protection from constrained high-risk trades",
      nextStep: "Run simulation on top risk lane before full rollout.",
      at: new Date().toISOString(),
    };

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">Autonomy Feedback</h2>
        {safeMode ? <span className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-200">System recovering</span> : null}
      </div>
      <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
        <div className="text-xs uppercase tracking-[0.14em] text-slate-500">Last executed action</div>
        <div className="mt-1 text-sm font-semibold text-slate-100">{action.title}</div>
        <div className="mt-2 text-xs text-emerald-300">{action.impact}</div>
        <div className="mt-2 text-xs text-slate-300">
          <span className="font-medium text-slate-200">Next step: </span>
          {action.nextStep}
        </div>
      </div>
      {safeMode ? (
        <p className="mt-3 text-xs text-slate-400">
          Using last known stable signal from {new Date(action.at || Date.now()).toLocaleTimeString()} while live feeds recover.
        </p>
      ) : null}
    </section>
  );
}
