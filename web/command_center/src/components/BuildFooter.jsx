import { getBuildInfo } from "../lib/version.js";

export default function BuildFooter() {
  const { version, gitSha } = getBuildInfo();
  return (
    <span className="cc-muted" style={{ fontSize: 11 }}>
      Command Center · v{version}
      {gitSha && gitSha !== "unknown" ? ` · ${gitSha}` : ""}
    </span>
  );
}
