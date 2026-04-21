/**
 * Post-build checks: output exists, exactly one hashed entry bundle, index references it.
 * Run after `vite build` (e.g. npm run build:validate).
 */
import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "..", "..", "static", "command_center");

async function main() {
  const errors = [];
  let files;
  try {
    files = await readdir(outDir);
  } catch (e) {
    console.error(`[validate-build] Cannot read ${outDir}:`, e.message);
    process.exit(1);
  }

  if (!files.includes("index.html")) {
    errors.push("Missing index.html in static/command_center");
  }

  const entryFiles = files.filter((f) => /^cc-app-[A-Za-z0-9_.-]+\.js$/.test(f));
  if (entryFiles.length !== 1) {
    errors.push(
      `Expected exactly one cc-app-[hash].js entry bundle, found ${entryFiles.length} (${entryFiles.join(", ") || "none"}) — clear static/command_center before build`,
    );
  }

  const entry = entryFiles[0];
  if (files.includes("index.html") && entry) {
    const html = await readFile(join(outDir, "index.html"), "utf8");
    if (!html.includes(entry)) {
      errors.push(`index.html does not reference ${entry} — stale index or partial deploy`);
    }
  }

  if (errors.length) {
    console.error("[validate-build] FAILED:");
    for (const m of errors) console.error(`  - ${m}`);
    process.exit(1);
  }

  console.log("[validate-build] OK:", { outDir, entry, fileCount: files.length });
}

main();
