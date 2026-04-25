import AIAssistantPanel from "../components/dashboard/AIAssistantPanel.jsx";

export default function BrainPage() {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-11rem)] max-w-3xl flex-col justify-center">
      <p className="mb-6 text-center text-sm text-slate-400">Signal steady. Command channel open.</p>
      <AIAssistantPanel />
    </div>
  );
}
