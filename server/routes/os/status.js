import express from 'express';
import { requireAuth } from '../../middleware/auth.js';
import { validateOSKey } from '../../middleware/validateOS.js';

const router = express.Router();

router.get('/api/os/:osKey/status', requireAuth, validateOSKey, async (req, res) => {
  const { osKey } = req.params;

  try {
    const metrics = await OSMetricsService.get(osKey, req.user.orgId);
    res.json({ osKey, status: 'active', metrics, updatedAt: new Date().toISOString() });
  } catch (err) {
    res.json({ osKey, status: 'degraded', metrics: null, error: err.message });
  }
});

function getStubMetrics(osKey) {
  const stubs = {
    personal:  { tasks_today: 0, focus_hours: 0 },
    business:  { revenue_today: 0, invoices_open: 0 },
    stock:     { signals_count: 0, risk_score: 0 },
    research:  { missions_active: 0, reports_ready: 0 },
    agentic:   { projects_active: 0, deploys_today: 0 },
  };
  return stubs[osKey] || {};
}

export default router;
