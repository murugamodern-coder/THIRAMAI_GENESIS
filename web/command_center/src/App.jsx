import { lazy, Suspense, useEffect } from "react";

import { logRenderStart, useLayoutCommitTrace, usePostCommitTrace } from "./lib/hookDebug.js";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

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
import PricingPage from "./pages/PricingPage.jsx";
import OnboardingPage from "./pages/OnboardingPage.jsx";
const InventoryPage = lazy(() => import("./pages/InventoryPage.jsx"));
const BillingPage = lazy(() => import("./pages/BillingPage.jsx"));
const ProductionPage = lazy(() => import("./pages/ProductionPage.jsx"));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage.jsx"));
const SettingsPage = lazy(() => import("./pages/SettingsPage.jsx"));
const CompanySelectPage = lazy(() => import("./pages/business/CompanySelectPage.jsx"));
const CompanyProfilePage = lazy(() => import("./pages/business/CompanyProfilePage.jsx"));
const ChartOfAccountsPage = lazy(() => import("./pages/business/ChartOfAccountsPage.jsx"));
const GSTPage = lazy(() => import("./pages/business/GSTPage.jsx"));
const PurchaseOrdersPage = lazy(() => import("./pages/business/PurchaseOrdersPage.jsx"));
const PayrollPage = lazy(() => import("./pages/business/PayrollPage.jsx"));
const ReportsPage = lazy(() => import("./pages/business/ReportsPage.jsx"));
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
import CentralBrainPage from "./pages/CentralBrainPage.jsx";
import StockOSPage from "./pages/StockOSPage.jsx";
import AgenticOSPage from "./pages/AgenticOSPage.jsx";
import { postUsageEvent } from "./api/commandCenterApi.js";

function Protected({ children }) {
  const token = useCommandStore((s) => s.token);
  return token ? children : <Navigate to="/login" replace />;
}

function ProtectedRoute({ children }) {
  return <Protected>{children}</Protected>;
}

function LegacyRouteRedirect({ to, from }) {
  const location = useLocation();
  useEffect(() => {
    postUsageEvent("legacy_route_redirect", {
      from: from || location.pathname,
      to,
      ts: Date.now(),
    }).catch(() => {});
  }, [from, location.pathname, to]);
  return <Navigate to={to} replace />;
}

export default function App() {
  logRenderStart("App");
  useLayoutCommitTrace("App");
  usePostCommitTrace("App");
  return (
    <Suspense fallback={<div className="cc-card">Loading page...</div>}>
      <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/pricing" element={<PricingPage />} />
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
        path="/central"
        element={
          <Protected>
            <Navigate to="/dashboard" replace />
          </Protected>
        }
      />
      <Route
        path="/dashboard"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<CentralBrainPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="stocks" element={<LegacyRouteRedirect from="/dashboard/stocks" to="/os/stock" />} />
        <Route path="website-builder" element={<LegacyRouteRedirect from="/dashboard/website-builder" to="/os/agentic-platform" />} />
        <Route path="research" element={<LegacyRouteRedirect from="/dashboard/research" to="/os/research" />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="production" element={<ProductionPage />} />
      </Route>
      <Route
        path="/stock"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<StockOSPage />} />
      </Route>
      <Route
        path="/research"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<ResearchPage />} />
      </Route>
      <Route
        path="/agentic"
        element={
          <Protected>
            <Navigate to="/os/agentic-platform" replace />
          </Protected>
        }
      />
      <Route
        path="/os"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="personal" element={<Navigate to="/personal" replace />} />
        <Route path="business" element={<Navigate to="/business" replace />} />
        <Route path="stock" element={<StockOSPage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="agentic-platform" element={<AgenticOSPage />} />
        <Route path="agentic" element={<Navigate to="/os/agentic-platform" replace />} />
      </Route>
      <Route
        path="/analytics"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<AnalyticsPage />} />
      </Route>
      <Route
        path="/settings"
        element={
          <Protected>
            <ShellLayout />
          </Protected>
        }
      >
        <Route index element={<SettingsPage />} />
      </Route>
      <Route
        path="/business"
        element={
          <ProtectedRoute>
            <CompanySelectPage />
          </ProtectedRoute>
        }
      />
<Route path="/business/:orgId/accounts" element={
  <Protected><ChartOfAccountsPage /></Protected>
} />
<Route path="/business/:orgId/gst" element={
  <Protected><GSTPage /></Protected>
} />
<Route path="/business/:orgId/purchase-orders" element={
  <Protected><PurchaseOrdersPage /></Protected>
} />
<Route path="/business/:orgId/payroll" element={
  <Protected><PayrollPage /></Protected>
} />
<Route path="/business/:orgId/reports" element={
  <Protected><ReportsPage /></Protected>
} />
      <Route
        path="/business/:orgId/profile"
        element={
          <Protected>
            <CompanyProfilePage />
          </Protected>
        }
      />
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
      <Route path="/agentic-platform" element={<LegacyRouteRedirect from="/agentic-platform" to="/os/agentic-platform" />} />
      <Route path="/os/stock/settings" element={<LegacyRouteRedirect from="/os/stock/settings" to="/os/stock" />} />
      <Route path="/os/research/settings" element={<LegacyRouteRedirect from="/os/research/settings" to="/os/research" />} />
      <Route path="/os/personal/settings" element={<LegacyRouteRedirect from="/os/personal/settings" to="/os/personal" />} />
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
    </Suspense>
  );
}
