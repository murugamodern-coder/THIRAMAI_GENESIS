import ComingSoonPage from "../../components/ComingSoonPage.jsx";

export default function ChartOfAccountsPage() {
  return (
    <ComingSoonPage
      title="Chart of Accounts"
      icon="??"
      description="Complete accounting structure for your business"
      expectedDate="Q3 2026"
      features={[
        "GST-ready account structure",
        "Auto-categorization",
        "P&L mapping",
        "Balance sheet ready",
      ]}
    />
  );
}
