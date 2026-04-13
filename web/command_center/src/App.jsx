import { Navigate, Route, Routes } from "react-router-dom";

import BusinessShellLayout from "./layout/BusinessShellLayout.jsx";
import BusinessBillingPage from "./pages/business/BusinessBillingPage.jsx";
import BusinessDashboardPage from "./pages/business/BusinessDashboardPage.jsx";
import BusinessExpensesPage from "./pages/business/BusinessExpensesPage.jsx";
import BusinessInventoryPage from "./pages/business/BusinessInventoryPage.jsx";
import BusinessProductionPage from "./pages/business/BusinessProductionPage.jsx";
import BusinessTasksPage from "./pages/business/BusinessTasksPage.jsx";

import { useCommandStore } from "./store/useCommandStore.js";
import ShellLayout from "./layout/ShellLayout.jsx";
import LandingPage from "./pages/LandingPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import OnboardingPage from "./pages/OnboardingPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import InventoryPage from "./pages/InventoryPage.jsx";
import BillingPage from "./pages/BillingPage.jsx";
import ProductionPage from "./pages/ProductionPage.jsx";
import PersonalShellLayout from "./layout/PersonalShellLayout.jsx";
import PersonalHomePage from "./pages/personal/PersonalHomePage.jsx";
import PersonalFinancePage from "./pages/personal/PersonalFinancePage.jsx";
import PersonalHealthPage from "./pages/personal/PersonalHealthPage.jsx";
import PersonalProductivityPage from "./pages/personal/PersonalProductivityPage.jsx";
import PersonalResearchPage from "./pages/personal/PersonalResearchPage.jsx";
import PersonalIntegrationsPage from "./pages/personal/PersonalIntegrationsPage.jsx";
import WeeklyReviewPage from "./pages/personal/WeeklyReviewPage.jsx";
import TodayPage from "./pages/TodayPage.jsx";
import CopilotPage from "./pages/CopilotPage.jsx";
import ResearchPage from "./pages/ResearchPage.jsx";

function Protected({ children }) {
  const token = useCommandStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route
        path="/onboarding"
        element={
          <Protected>
            <OnboardingPage />
          </Protected>
        }
      />
      <Route
        path="/today"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<TodayPage />} />
      </Route>
      <Route
        path="/dashboard"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="production" element={<ProductionPage />} />
      </Route>
      <Route
        path="/business/:orgId"
        element={
          <Protected>
            <BusinessShellLayout />
          </Protected>
        }
      >
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<BusinessDashboardPage />} />
        <Route path="inventory" element={<BusinessInventoryPage />} />
        <Route path="billing" element={<BusinessBillingPage />} />
        <Route path="expenses" element={<BusinessExpensesPage />} />
        <Route path="production" element={<BusinessProductionPage />} />
        <Route path="tasks" element={<BusinessTasksPage />} />
      </Route>
      <Route
        path="/ai"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<CopilotPage />} />
      </Route>
      <Route
        path="/personal"
        element={
          <Protected>
            <PersonalShellLayout />
          </Protected>
        }
      >
        <Route index element={<PersonalHomePage />} />
        <Route path="finance" element={<PersonalFinancePage />} />
        <Route path="health" element={<PersonalHealthPage />} />
        <Route path="productivity" element={<PersonalProductivityPage />} />
        <Route path="research" element={<PersonalResearchPage />} />
        <Route path="integrations" element={<PersonalIntegrationsPage />} />
        <Route path="weekly-review" element={<WeeklyReviewPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
