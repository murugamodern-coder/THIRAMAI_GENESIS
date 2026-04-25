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
const AutomationPage = lazy(() => import("./pages/AutomationPage.jsx"));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage.jsx"));
const OpportunitiesPage = lazy(() => import("./pages/OpportunitiesPage.jsx"));
const LearningInsightsPage = lazy(() => import("./pages/LearningInsightsPage.jsx"));
const ControlCenterPage = lazy(() => import("./pages/ControlCenterPage.jsx"));
const MoneyLoopPage = lazy(() => import("./pages/MoneyLoopPage.jsx"));
const WarRoomPage = lazy(() => import("./pages/WarRoomPage.jsx"));
const ResearchProjectsPage = lazy(() => import("./pages/ResearchProjectsPage.jsx"));
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
import StockOSPage from "./pages/StockOSPage.jsx";
import AgenticOSPage from "./pages/AgenticOSPage.jsx";
import BrainPage from "./pages/BrainPage.jsx";
import { fetchAuthMe, postUsageEvent } from "./api/commandCenterApi.js";
import { clearAuthStorage } from "./api/client.js";
import { defaultRouteForRole, ROLES } from "./lib/rbac.js";

const ENABLE_FOCUS_MODE = true;
const FOCUS_HOME = "/command-center";

function Protected({ children }) {
  const token = useCommandStore((s) => s.token);
  return token ? children : <Navigate to="/login" replace />;
}

function RoleProtected({ allow, children }) {
  const me = useCommandStore((s) => s.me);
  const role = useCommandStore((s) => s.role);
  if (!me) return children;
  return allow.includes(role) ? children : <Navigate to={defaultRouteForRole(role)} replace />;
}

function ProtectedRoute({ children }) {
  return <Protected>{children}</Protected>;
}

function FocusRedirect() {
  return (
    <Protected>
      <Navigate to={FOCUS_HOME} replace />
    </Protected>
  );
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
  const token = useCommandStore((s) => s.token);
  const setMe = useCommandStore((s) => s.setMe);
  const logout = useCommandStore((s) => s.logout);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetchAuthMe()
      .then((me) => {
        if (!cancelled && me) setMe(me);
      })
      .catch((err) => {
        const status = Number(err?.response?.status || 0);
        if (status === 401) {
          clearAuthStorage();
          logout();
          if (typeof window !== "undefined") window.location.hash = "#/login";
        }
      });
    return () => {
      cancelled = true;
    };
  }, [logout, setMe, token]);

  return (
    <Suspense fallback={<div className="cc-card">Loading page...</div>}>
      <Routes>
      <Route path="/" element={token ? <Navigate to={FOCUS_HOME} replace /> : <LandingPage />} />
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
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<TodayPage />} />
      </Route>
      <Route
        path="/command-center"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<BrainPage />} />
      </Route>
      <Route
        path="/central"
        element={
          <Protected>
            <Navigate to={ENABLE_FOCUS_MODE ? FOCUS_HOME : "/brain"} replace />
          </Protected>
        }
      />
      <Route
        path="/brain"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<BrainPage />} />
      </Route>
      <Route
        path="/automation"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<AutomationPage />} />
      </Route>
      <Route
        path="/integrations"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<IntegrationsPage />} />
      </Route>
      <Route
        path="/opportunities"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<OpportunitiesPage />} />
      </Route>
      <Route
        path="/learning"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<LearningInsightsPage />} />
      </Route>
      <Route
        path="/control-center"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<ControlCenterPage />} />
      </Route>
      <Route
        path="/os/control-center"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<ControlCenterPage />} />
      </Route>
      <Route
        path="/money-loop"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<MoneyLoopPage />} />
      </Route>
      <Route
        path="/war-room"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<WarRoomPage />} />
      </Route>
      <Route
        path="/research-projects"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<ResearchProjectsPage />} />
      </Route>
      <Route
        path="/dashboard"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<Navigate to={FOCUS_HOME} replace />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="stocks" element={<LegacyRouteRedirect from="/dashboard/stocks" to="/os/stock" />} />
        <Route
          path="website-builder"
          element={
            ENABLE_FOCUS_MODE ? (
              <Navigate to={FOCUS_HOME} replace />
            ) : (
              <LegacyRouteRedirect from="/dashboard/website-builder" to="/os/agentic-platform" />
            )
          }
        />
        <Route
          path="research"
          element={
            ENABLE_FOCUS_MODE ? (
              <Navigate to={FOCUS_HOME} replace />
            ) : (
              <LegacyRouteRedirect from="/dashboard/research" to="/os/research" />
            )
          }
        />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="production" element={<ProductionPage />} />
      </Route>
      <Route
        path="/stock"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<StockOSPage />} />
      </Route>
      <Route
        path="/research"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <Protected>
              <RoleProtected allow={[ROLES.OWNER]}>
                <ShellLayout />
              </RoleProtected>
            </Protected>
          )
        }
      >
        <Route index element={<ResearchPage />} />
      </Route>
      <Route
        path="/agentic"
        element={
          <Protected>
            <Navigate to={ENABLE_FOCUS_MODE ? FOCUS_HOME : "/os/agentic-platform"} replace />
          </Protected>
        }
      />
      <Route
        path="/os"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<Navigate to={FOCUS_HOME} replace />} />
        <Route path="personal" element={<Navigate to="/personal" replace />} />
        <Route path="business" element={<Navigate to="/business" replace />} />
        <Route path="stock" element={<StockOSPage />} />
        <Route path="research" element={ENABLE_FOCUS_MODE ? <Navigate to={FOCUS_HOME} replace /> : <ResearchPage />} />
        <Route
          path="agentic-platform"
          element={ENABLE_FOCUS_MODE ? <Navigate to={FOCUS_HOME} replace /> : <AgenticOSPage />}
        />
        <Route path="agentic" element={<Navigate to={ENABLE_FOCUS_MODE ? FOCUS_HOME : "/os/agentic-platform"} replace />} />
      </Route>
      <Route
        path="/analytics"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<AnalyticsPage />} />
      </Route>
      <Route
        path="/settings"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<SettingsPage />} />
      </Route>
      <Route
        path="/business"
        element={
          <ProtectedRoute>
            <RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}>
              <CompanySelectPage />
            </RoleProtected>
          </ProtectedRoute>
        }
      />
<Route path="/business/:orgId/accounts" element={
  <Protected><RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}><ChartOfAccountsPage /></RoleProtected></Protected>
} />
<Route path="/business/:orgId/gst" element={
  <Protected><RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}><GSTPage /></RoleProtected></Protected>
} />
<Route path="/business/:orgId/purchase-orders" element={
  <Protected><RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}><PurchaseOrdersPage /></RoleProtected></Protected>
} />
<Route path="/business/:orgId/payroll" element={
  <Protected><RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}><PayrollPage /></RoleProtected></Protected>
} />
<Route path="/business/:orgId/reports" element={
  <Protected><RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}><ReportsPage /></RoleProtected></Protected>
} />
      <Route
        path="/business/:orgId/profile"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}>
              <CompanyProfilePage />
            </RoleProtected>
          </Protected>
        }
      />
      <Route
        path="/business/:orgId"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER, ROLES.STAFF]}>
              <BusinessShellLayout />
            </RoleProtected>
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
            <RoleProtected allow={[ROLES.OWNER]}>
              <ShellLayout />
            </RoleProtected>
          </Protected>
        }
      >
        <Route index element={<CopilotPage />} />
      </Route>
      <Route
        path="/agentic-platform"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <LegacyRouteRedirect from="/agentic-platform" to="/os/agentic-platform" />
          )
        }
      />
      <Route path="/os/stock/settings" element={<LegacyRouteRedirect from="/os/stock/settings" to="/os/stock" />} />
      <Route
        path="/os/research/settings"
        element={
          ENABLE_FOCUS_MODE ? (
            <FocusRedirect />
          ) : (
            <LegacyRouteRedirect from="/os/research/settings" to="/os/research" />
          )
        }
      />
      <Route path="/os/personal/settings" element={<LegacyRouteRedirect from="/os/personal/settings" to="/os/personal" />} />
      <Route
        path="/personal"
        element={
          <Protected>
            <RoleProtected allow={[ROLES.OWNER, ROLES.FAMILY]}>
              <PersonalShellLayout />
            </RoleProtected>
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
