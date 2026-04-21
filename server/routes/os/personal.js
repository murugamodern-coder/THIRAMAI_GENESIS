const express = require('express');
const router = express.Router();

router.get('/api/os/personal/tasks', requireAuth, async (req, res) => {
  const apiKey = await getOSSetting(req.user.orgId, 'personal', 'lindy_api_key');
  if (!apiKey) return res.json({ connected: false, tasks: [], message: 'Connect Lindy.ai in Settings' });

  const lindy = new LindyService(apiKey);
  const result = await lindy.getTasks();
  res.json({ connected: true, ...result });
});

router.get('/api/os/personal/schedule', requireAuth, async (req, res) => {
  // Motion API — stub for now, add Motion key in next step
  res.json({ connected: false, events: [], message: 'Connect Motion in Settings' });
});

module.exports = router;