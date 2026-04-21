/** Best-effort: first frame from React 17+ `at Name` or legacy `in Name`. */
export function parseFailingComponentFrame(componentStack) {
  if (!componentStack || typeof componentStack !== "string") return null;
  const lines = componentStack
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  for (const line of lines) {
    const at = line.match(/^\s*at\s+([^\s(]+)/);
    if (at) return { raw: line, name: at[1] };
    const inn = line.match(/\bin\s+([^\s(]+)/);
    if (inn) return { raw: line, name: inn[1] };
  }
  return null;
}
