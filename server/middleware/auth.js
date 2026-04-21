export function requireAuth(req, res, next) {
  if (!req.session?.userId) {
    return res.status(401).json({
      ok: false,
      error: 'Unauthorised',
      code: 'AUTH_REQUIRED'
    });
  }
  next();
}

export function requireRole(role) {
  return (req, res, next) => {
    if (!req.user) return res.status(401).json({ ok: false, error: 'Unauthorised' });
    if (req.user.role !== role && req.user.role !== 'admin') {
      return res.status(403).json({ ok: false, error: 'Forbidden', code: 'ROLE_REQUIRED' });
    }
    next();
  };
}
