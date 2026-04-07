export function parseInr(s) {
  if (s == null || s === "") return 0;
  if (typeof s === "number" && !Number.isNaN(s)) return s;
  const n = parseFloat(String(s).replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

export function gstTotal(gstBlock) {
  if (!gstBlock || typeof gstBlock !== "object") return 0;
  return ["cgst", "sgst", "igst"].reduce((a, k) => a + parseInr(gstBlock[k]), 0);
}
