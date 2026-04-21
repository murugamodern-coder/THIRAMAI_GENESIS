const express = require('express');
const router = express.Router();

router.get('/api/today', requireAuth, async (req, res) => {
  try {
    const summary = await buildTodaySummary(req.user.orgId);
    res.json({ ok: true, data: summary });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

async function buildTodaySummary(orgId) {
  const [tasks, events, decisions] = await Promise.all([
    db.tasks.countToday(orgId),
    db.events.listToday(orgId),
    db.aiDecisions.countPending(orgId),
  ]);
  return { tasks, events, decisions, generatedAt: new Date().toISOString() };
}

module.exports = router;