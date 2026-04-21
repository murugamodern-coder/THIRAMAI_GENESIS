import OpenAI from 'openai';
import express from 'express';
const router = express.Router();

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const JARVIS_SYSTEM_PROMPT = `You are Jarvis, the AI decision engine for THIRAMAI
— a Personal Agentic Operating System with 5 modules:
1. Personal OS (scheduling, memory, automation)
2. Business OS (trading, manufacturing, GST, ERP)
3. Stock OS (market intelligence, 4-point analysis)
4. Research OS (multi-AI research pipeline)
5. Agentic Web OS (build, deploy, monitor)

Be concise. Give actionable answers. If you need data you don't have,
say what integration is needed to get it.
Always respond in the same language the user wrote in.`;

router.post('/api/jarvis/ask', requireAuth, async (req, res) => {
  const { question, context, osKey } = req.body;

  // Validate input
  if (!question || typeof question !== 'string') {
    return res.status(400).json({ ok: false, error: 'question must be a non-empty string' });
  }
  if (question.length > 2000) {
    return res.status(400).json({ ok: false, error: 'question too long (max 2000 chars)' });
  }
  // Sanitise — strip any HTML
  const safeQuestion = question.replace(/<[^>]*>/g, '').trim();

  if (!process.env.OPENAI_API_KEY) {
    return res.json({
      answer: 'OpenAI API key not configured. Add OPENAI_API_KEY to server/.env',
      configured: false
    });
  }

  try {
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o',
      max_tokens: 500,
      messages: [
        { role: 'system', content: JARVIS_SYSTEM_PROMPT },
        { role: 'user', content: `Context: ${osKey || context || 'dashboard'}\n\nQuestion: ${safeQuestion}` }
      ]
    });

    res.json({
      answer: completion.choices[0].message.content,
      model: completion.model,
      configured: true,
      timestamp: new Date().toISOString()
    });
  } catch (err) {
    res.status(500).json({ error: err.message, configured: true });
  }
});

export default router;
