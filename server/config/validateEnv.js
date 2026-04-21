const REQUIRED_IN_PRODUCTION = [
  'SESSION_SECRET',
  'CLIENT_URL',
  'OPENAI_API_KEY',
];

export function validateEnv() {
  const isProd = process.env.NODE_ENV === 'production';

  if (isProd) {
    const missing = REQUIRED_IN_PRODUCTION.filter(k => !process.env[k]);
    if (missing.length > 0) {
      throw new Error(
        `Missing required environment variables: ${missing.join(', ')}\n` +
        'Set these in your production environment before starting.'
      );
    }
  }

  // Warn about defaults
  if (process.env.SESSION_SECRET?.includes('change-this')) {
    console.warn('[WARN] SESSION_SECRET is using default value — change before production!');
  }
  if (!process.env.OPENAI_API_KEY) {
    console.warn('[WARN] OPENAI_API_KEY not set — Jarvis will use stub responses');
  }

  console.log('[CONFIG] Environment validated ✓');
}
