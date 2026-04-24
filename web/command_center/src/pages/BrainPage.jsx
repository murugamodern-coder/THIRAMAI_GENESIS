import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";

export default function BrainPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="mb-2 text-xl font-semibold text-slate-100">Brain</h1>
        <p className="text-sm text-slate-400">Jarvis AI workspace for decisions and execution.</p>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <AIAssistantPanel />
      </div>
    </div>
  );
}
