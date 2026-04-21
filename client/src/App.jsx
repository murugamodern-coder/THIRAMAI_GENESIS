import React, { useEffect, useMemo } from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation } from 'react-router-dom';
import ThiraiDashboard from './pages/Dashboard/Dashboard';
import { ErrorBoundary } from './components/ErrorBoundary';

function resolveCommandCenterPath(pathname) {
  if (pathname.startsWith('/settings/os/personal')) return '/os/personal';
  if (pathname.startsWith('/settings/os/stock')) return '/os/stock';
  if (pathname.startsWith('/settings/os/research')) return '/os/research';
  if (pathname.startsWith('/settings/os/agentic')) return '/os/agentic-platform';
  if (pathname.startsWith('/os/agentic')) return '/os/agentic-platform';
  if (pathname.startsWith('/os/personal')) return '/os/personal';
  if (pathname.startsWith('/os/business')) return '/os/business';
  if (pathname.startsWith('/os/stock')) return '/os/stock';
  if (pathname.startsWith('/os/research')) return '/os/research';
  if (pathname === '/today') return '/today';
  return '/dashboard';
}

function CommandCenterBridgeRedirect() {
  const location = useLocation();
  const target = useMemo(() => {
    const ccPath = resolveCommandCenterPath(location.pathname);
    const search = location.search || '';
    return `/static/command_center/#${ccPath}${search}`;
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.location.replace(target);
    }
  }, [target]);

  return <div style={{ padding: 24 }}>Redirecting to THIRAMAI Command Center...</div>;
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" />} />
        <Route path="/dashboard" element={<ErrorBoundary><ThiraiDashboard /></ErrorBoundary>} />
        <Route path="/today" element={<CommandCenterBridgeRedirect />} />
        <Route path="/settings/os/:module" element={<CommandCenterBridgeRedirect />} />
        <Route path="/os/*" element={<CommandCenterBridgeRedirect />} />
        <Route path="/agentic" element={<Navigate to="/os/agentic-platform" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" />} />
      </Routes>
    </Router>
  );
}

export default App;
