import express from 'express';
import cors from 'cors';
import session from 'express-session';
import helmet from 'helmet';
import rateLimit from 'express-rate-limit';
import morgan from 'morgan';
import dotenv from 'dotenv';
import { validateEnv } from './config/validateEnv.js';
dotenv.config();

validateEnv(); // Ensure environment is validated before starting

import { requireAuth } from './middleware/auth.js';
import todayRouter from './routes/today.js';
import jarvisRouter from './routes/jarvis.js';
import osStatusRouter from './routes/os/status.js';
import osSettingsRouter from './routes/os/settings.js';
import personalRouter from './routes/os/personal.js';
import stockRouter from './routes/os/stock.js';
import researchRouter from './routes/os/research.js';

const app = express();
const PORT = process.env.PORT || 4000;
const isDev = process.env.NODE_ENV !== 'production';

// Security headers (OWASP A05)
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", "data:", "https:"],
      connectSrc: ["'self'", "https://api.openai.com",
                   "https://api.perplexity.ai",
                   "https://api.quiverquant.com",
                   "https://api.lindy.ai"],
    },
  },
  crossOriginEmbedderPolicy: false,
}));

// Request logging
app.use(morgan(isDev ? 'dev' : 'combined'));

// Rate limiting (OWASP A04)
const globalLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 200,
  standardHeaders: true,
  legacyHeaders: false,
  message: { ok: false, error: 'Too many requests', code: 'RATE_LIMITED' }
});
const jarvisLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 10, // max 10 Jarvis calls per minute per IP
  message: { ok: false, error: 'Jarvis rate limit reached', code: 'JARVIS_RATE_LIMITED' }
});
app.use(globalLimiter);

// CORS — only allow client origin (OWASP A07)
app.use(cors({
  origin: process.env.CLIENT_URL || 'http://localhost:3000',
  credentials: true,
  methods: ['GET', 'POST', 'PATCH', 'DELETE'],
  allowedHeaders: ['Content-Type', 'Authorization'],
}));

// Body parsing with size limit (OWASP A08)
app.use(express.json({ limit: '10kb' }));
app.use(express.urlencoded({ extended: true, limit: '10kb' }));

// Session
app.use(session({
  secret: process.env.SESSION_SECRET || (() => {
    if (!isDev) throw new Error('SESSION_SECRET must be set in production');
    return 'thiramai-dev-only-secret-change-in-prod';
  })(),
  resave: false,
  saveUninitialized: false,
  cookie: {
    secure: !isDev,      // HTTPS only in production
    httpOnly: true,      // No JS access to cookie
    sameSite: 'strict',  // CSRF protection
    maxAge: 24 * 60 * 60 * 1000, // 24 hours
  }
}));

// Dev auth bypass (REMOVE IN PRODUCTION — replace with real session auth)
if (isDev) {
  app.use((req, res, next) => {
    req.session.userId = 1;
    req.user = {
      id: 1, orgId: 1, role: 'admin',
      email: 'admin_now@provisioned.thiramai.local'
    };
    next();
  });
}

// Routes
app.use('/api', todayRouter);
app.use('/api', jarvisLimiter, jarvisRouter);
app.use('/api', osStatusRouter);
app.use('/api', osSettingsRouter);
app.use('/api', personalRouter);
app.use('/api', stockRouter);
app.use('/api', researchRouter);

// Health check (no auth needed)
app.get('/api/health', (req, res) => res.json({
  status: 'ok',
  version: process.env.npm_package_version || '3.0.0',
  env: process.env.NODE_ENV || 'development',
  timestamp: new Date().toISOString(),
}));

// 404 handler
app.use((req, res) => res.status(404).json({
  ok: false, error: 'Endpoint not found', path: req.path
}));

// Global error handler (OWASP A09 — don't leak stack traces)
app.use((err, req, res, next) => {
  console.error('[ERROR]', err.message, isDev ? err.stack : '');
  res.status(err.status || 500).json({
    ok: false,
    error: isDev ? err.message : 'Internal server error',
    code: err.code || 'INTERNAL_ERROR',
  });
});

app.listen(PORT, () => {
  console.log(`THIRAMAI server v3.0 running on port ${PORT}`);
  console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
  console.log(`OpenAI: ${process.env.OPENAI_API_KEY ? 'configured' : 'NOT SET'}`);
});

export default app;
