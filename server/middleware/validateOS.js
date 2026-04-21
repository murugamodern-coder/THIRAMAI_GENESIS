const VALID_OS_KEYS = ['personal', 'business', 'stock', 'research', 'agentic'];

export function validateOSKey(req, res, next) {
  const { osKey } = req.params;
  if (!VALID_OS_KEYS.includes(osKey)) {
    return res.status(400).json({
      ok: false,
      error: 'Invalid OS key',
      valid: VALID_OS_KEYS,
    });
  }
  next();
}
