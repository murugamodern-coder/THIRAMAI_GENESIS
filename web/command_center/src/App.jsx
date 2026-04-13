import { Navigate, Route, Routes } from "react-router-dom";

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
import TodayPage from "./pages/TodayPage.jsx";

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
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="production" element={<ProductionPage />} />
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
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
