const STATE_STYLES = {
  ACTIVE: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  DEGRADED: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  CRITICAL: "border-red-500/40 bg-red-500/10 text-red-200",
};

function StatChip({ label, value, emphasis = false }) {
  return (
    <div className={`rounded-xl border px-3 py-2 ${emphasis ? "border-blue-500/40 bg-blue-500/10" : "border-slate-700 bg-slate-900/70"}`}>
      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-400">{label}</div>
      <div className={`mt-1 text-base font-semibold ${emphasis ? "text-blue-200" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

export default function SystemBar({ state, risks, opportunities, confidence }) {
  const s = String(state || "DEGRADED").toUpperCase();
  const style = STATE_STYLES[s] || STATE_STYLES.DEGRADED;
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 shadow-[0_0_0_1px_rgba(148,163,184,0.08)]">
      <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr_1fr_1fr]">
        <div className={`rounded-xl border px-3 py-2 ${style}`}>
          <div className="text-[11px] uppercase tracking-[0.14em]">System State</div>
          <div className="mt-1 text-lg font-semibold">{s}</div>
        </div>
        <StatChip label="Risks" value={Number(risks || 0)} />
        <StatChip label="Opportunities" value={Number(opportunities || 0)} />
        <StatChip label="Confidence" value={`${Math.max(0, Math.min(100, Number(confidence || 0))).toFixed(0)}%`} emphasis />
      </div>
    </section>
  );
}
