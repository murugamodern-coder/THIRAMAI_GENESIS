import ComingSoonPage from "../../components/ComingSoonPage.jsx";

export default function GSTPage() {
  return (
    <ComingSoonPage
      title="GST Filing"
      icon="???"
      description="Automated GST returns and compliance"
      expectedDate="Q3 2026"
      features={[
        "GSTR-1, GSTR-3B auto-fill",
        "Input tax credit tracking",
        "E-invoice generation",
        "Direct filing integration",
      ]}
    />
  );
}
