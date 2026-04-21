export const OS_REGISTRY = [
  {
    key: 'personal',
    name: 'Personal OS',
    subtitle: 'Life Operating System',
    icon: 'user',
    accentColor: '#1D9E75',
    route: '/os/personal',
    stats: [
      { label: 'Tasks today', apiKey: 'tasks_today' },
      { label: 'Focus hours', apiKey: 'focus_hours' },
    ],
    integrations: ['Lindy.ai', 'Motion', 'Reclaim', 'Recall', 'Rewind'],
  },
  {
    key: 'business',
    name: 'Business OS',
    subtitle: 'Companies · ERP',
    icon: 'building',
    accentColor: '#378ADD',
    route: '/os/business',
    stats: [
      { label: 'Revenue today', apiKey: 'revenue_today' },
      { label: 'Open invoices', apiKey: 'invoices_open' },
    ],
    integrations: ['GST Portal', 'Tally', 'Banking API', 'Gov Schemes'],
  },
  {
    key: 'stock',
    name: 'Stock OS',
    subtitle: 'Market Intelligence',
    icon: 'trending-up',
    accentColor: '#BA7517',
    route: '/os/stock',
    stats: [
      { label: 'Signals today', apiKey: 'signals_count' },
      { label: 'Risk score', apiKey: 'risk_score' },
    ],
    integrations: ['Bloomberg', 'Aladdin', 'Quiver Quant', 'FlightRadar'],
    /** When true, UI may surface Plan→Approve→Execute (see Dashboard `AgentApprovalPanel`). */
    features: { agentApprovalWorkflow: true },
  },
  {
    key: 'research',
    name: 'Research OS',
    subtitle: 'Multi-AI Research Crew',
    icon: 'search',
    accentColor: '#D85A30',
    route: '/os/research',
    stats: [
      { label: 'Active missions', apiKey: 'missions_active' },
      { label: 'Reports ready', apiKey: 'reports_ready' },
    ],
    integrations: ['Perplexity', 'StormAI', 'GPT-5', 'CrewAI'],
  },
  {
    key: 'agentic',
    name: 'Agentic Web OS',
    subtitle: 'Agentic Platform',
    icon: 'cpu',
    accentColor: '#993556',
    route: '/os/agentic',
    stats: [
      { label: 'Active projects', apiKey: 'projects_active' },
      { label: 'Deployments', apiKey: 'deploys_today' },
    ],
    integrations: ['Replit', 'Cursor', 'Lovable', 'bolt.new', 'v0.dev'],
  },
];