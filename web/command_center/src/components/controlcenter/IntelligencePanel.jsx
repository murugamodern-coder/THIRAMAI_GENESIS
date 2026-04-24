function InsightCard({ item }) {
  return (
    <article className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-100">{item.title}</h3>
        <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-xs text-blue-200">
          {Math.round(Number(item.confidence || 0))}%
        </span>
      </div>
      <p className="mt-2 text-xs text-slate-300">{item.why}</p>
      <div className="mt-2 text-xs text-slate-400">
        <span className="font-medium text-slate-200">Recommended: </span>
        {item.action}
      </div>
    </article>
  );
}

export default function IntelligencePanel({ opportunities = [], threats = [] }) {
  const liveOpportunities = opportunities.length
    ? opportunities
    : [
        {
          id: "op_fallback_1",
          title: "Supplier arbitrage window",
          why: "Regional input costs diverged by 8% in the last 24h.",
          action: "Allocate rapid buy mission to lowest volatility lane.",
          confidence: 71,
        },
      ];
  const liveThreats = threats.length
    ? threats
    : [
        {
          id: "th_fallback_1",
          title: "Execution latency spike",
          why: "Observed higher-than-baseline decision cycle time.",
          action: "Switch to guarded execution profile and monitor retries.",
          confidence: 68,
        },
      ];

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">Live Intelligence</h2>
        <span className="text-xs text-slate-500">Opportunity + Threat stream</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-300">Opportunities</div>
          {liveOpportunities.slice(0, 3).map((item) => (
            <InsightCard key={item.id} item={item} />
          ))}
        </div>
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-red-300">Threats</div>
          {liveThreats.slice(0, 3).map((item) => (
            <InsightCard key={item.id} item={item} />
          ))}
        </div>
      </div>
    </section>
  );
}
