import ComingSoonPage from "../../components/ComingSoonPage.jsx";

export default function PurchaseOrdersPage() {
  return (
    <ComingSoonPage
      title="Purchase Orders"
      icon="??"
      description="End-to-end procurement management"
      expectedDate="Q2 2026"
      features={[
        "PO creation and tracking",
        "Supplier management",
        "3-way matching",
        "Auto-invoice generation",
      ]}
    />
  );
}
