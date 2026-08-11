import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const assetsDir = path.resolve("dist", "assets");
const forbiddenChunks = [
  "AnalyticsPage",
  "ClassifierPage",
  "IntegrationsPage",
  "MemoryPage",
  "SensoryPage",
  "StreamStudioPage",
  "YouTubeStudioPage",
];

const files = await readdir(assetsDir);
const failures = [];

for (const file of files) {
  if (file.endsWith(".map")) {
    failures.push(`source map emitted: ${file}`);
  }
  if (forbiddenChunks.some((name) => file.includes(name))) {
    failures.push(`owner-only chunk emitted in clipper build: ${file}`);
  }
  if (file.endsWith(".js")) {
    const text = await readFile(path.join(assetsDir, file), "utf8");
    if (text.includes("sourceMappingURL=")) {
      failures.push(`sourceMappingURL reference emitted: ${file}`);
    }
  }
}

if (failures.length) {
  console.error("Clipper bundle check failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("Clipper bundle check passed.");
