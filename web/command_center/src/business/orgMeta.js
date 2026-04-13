/** Expected mapping for your four operating companies (IDs are tenant-specific; hints for UI only). */
export const BUSINESS_ORG_HINTS = {
  1: { label: "Mass Success Agro Agency", subsidy: true, gst: true },
  2: { label: "Modern Corporation", subsidy: false, gst: true },
  3: { label: "Lakshmi Hollow Bricks", subsidy: false, gst: false },
  4: { label: "Food Manufacturing", subsidy: false, gst: true },
};

export function hintForOrg(orgId) {
  return BUSINESS_ORG_HINTS[Number(orgId)] || null;
}

export function orgUsesGst(orgId) {
  const h = hintForOrg(orgId);
  if (h) return !!h.gst;
  return true;
}
