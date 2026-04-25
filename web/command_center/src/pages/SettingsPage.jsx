import ComingSoonPage from "../components/ComingSoonPage.jsx";

export default function SettingsPage() {
  return (
    <ComingSoonPage
      title="Settings"
      icon="??"
      description="Full system configuration and preferences"
      expectedDate="Q2 2026"
      features={[
        "Account management",
        "Notification preferences",
        "Integration settings",
        "Security controls",
      ]}
    />
  );
}
