import ComingSoonPage from "../../components/ComingSoonPage.jsx";

export default function ReportsPage() {
  return (
    <ComingSoonPage
      title="Reports"
      icon="??"
      description="Comprehensive business reporting suite"
      expectedDate="Q2 2026"
      features={[
        "P&L statements",
        "Cash flow reports",
        "Inventory reports",
        "Custom report builder",
      ]}
    />
  );
}
