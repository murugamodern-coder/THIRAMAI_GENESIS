const express = require('express');
const router = express.Router();

router.get('/api/os/stock/signals', requireAuth, async (req, res) => {
  const apiKey = await getOSSetting(req.user.orgId, 'stock', 'quiver_api_key');
  if (!apiKey) return res.json({ connected: false, signals: [] });

  try {
    const quiver = new QuiverService(apiKey);
    const watchlist = await getWatchlist(req.user.orgId); // user's stock watchlist
    const signals = [];

    for (const ticker of watchlist.slice(0, 3)) { // limit to 3 to avoid rate limit
      const [congress, sentiment] = await Promise.all([
        quiver.getCongressTrading(ticker),
        quiver.getSentiment(ticker)
      ]);
      signals.push({ ticker, congress, sentiment });
    }

    res.json({ connected: true, signals, updatedAt: new Date().toISOString() });
  } catch (err) {
    res.status(500).json({ connected: true, error: err.message, signals: [] });
  }
});

module.exports = router;