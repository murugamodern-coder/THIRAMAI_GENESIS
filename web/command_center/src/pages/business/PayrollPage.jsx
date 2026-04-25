import ComingSoonPage from "../../components/ComingSoonPage.jsx";

export default function PayrollPage() {
  return (
    <ComingSoonPage
      title="Payroll"
      icon="??"
      description="Complete payroll management with compliance"
      expectedDate="Q3 2026"
      features={[
        "Salary processing",
        "PF/ESI calculations",
        "Payslip generation",
        "TDS management",
      ]}
    />
  );
}
