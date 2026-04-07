export const AI_MOCK_INSIGHTS = [
  {
    id: "insight_1",
    title: "Inventory shortage risk",
    description: "Stock for HDPE granules is projected to run out in ~3 days at current consumption.",
    priority: "high",
    confidence: 0.87,
    actions: [
      {
        label: "Create reorder (add inventory)",
        type: "inventory_reorder",
        payload: { name: "HDPE granules", quantity: 100, unit: "kg" },
      },
    ],
  },
  {
    id: "insight_2",
    title: "Pending approvals slowing execution",
    description: "Multiple high-impact decisions are pending approval. Clearing them can unlock automation.",
    priority: "medium",
    confidence: 0.74,
    actions: [
      {
        label: "Open Mission Hub",
        type: "navigate",
        payload: { to: "/dashboard" },
      },
    ],
  },
];
