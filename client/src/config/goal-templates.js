/** Goal UX: reusable templates + autocomplete strings (client-only). */

export const GOAL_MIN_CHARS = 18;
export const GOAL_MIN_WORDS = 4;

export const GOAL_EXAMPLES = [
  'Analyze my business performance',
  'Check system health',
  'Optimize expenses',
];

/** Short labels → full goal text */
export const GOAL_TEMPLATES = [
  {
    id: 'biz-performance',
    label: 'Business performance',
    text:
      'Analyze my business performance for the last quarter: summarize KPIs, risks, and three concrete improvements.',
  },
  {
    id: 'system-health',
    label: 'System health',
    text:
      'Check system health end-to-end: verify services, queues, workers, and report any anomalies with severity.',
  },
  {
    id: 'optimize-expenses',
    label: 'Expense optimization',
    text:
      'Review and optimize expenses: categorize spend, flag waste, and propose a prioritized savings plan.',
  },
  {
    id: 'inventory-audit',
    label: 'Inventory audit',
    text:
      'Audit inventory levels and turnover: highlight stockouts, overstocks, and reorder suggestions.',
  },
];

/** Datalist options for browser autocomplete */
export const GOAL_SUGGESTIONS = [
  ...GOAL_EXAMPLES,
  ...GOAL_TEMPLATES.map((t) => t.text),
  'Prepare a weekly executive summary with risks and next actions',
  'Review compliance posture and list gaps with remediation steps',
];

export function validateGoalText(raw) {
  const g = String(raw || '').trim();
  if (!g) {
    return { ok: false, message: 'Enter a goal before running.' };
  }
  const words = g.split(/\s+/).filter(Boolean);
  if (words.length < GOAL_MIN_WORDS) {
    return {
      ok: false,
      message: `Describe your goal in at least ${GOAL_MIN_WORDS} words so THIRAMAI can plan clearly.`,
    };
  }
  if (g.length < GOAL_MIN_CHARS) {
    return {
      ok: false,
      message: `Goals under ${GOAL_MIN_CHARS} characters are usually too vague — add context (what, scope, outcome).`,
    };
  }
  const letters = g.replace(/[^a-zA-Z\u00C0-\u024F]/g, '');
  if (letters.length < 12) {
    return {
      ok: false,
      message: 'This goal looks unclear — use a short sentence with real words (not only symbols or numbers).',
    };
  }
  return { ok: true, goal: g };
}
