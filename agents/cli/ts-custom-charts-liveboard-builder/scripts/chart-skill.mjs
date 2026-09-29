// Finds the ts-custom-charts-builder skill, which owns the chart library, the shared core and the
// browser helpers this skill builds on. Order: $TS_CUSTOM_CHARTS_SKILL, then a sibling folder
// (both skills installed side by side under .claude/skills/), under either of its published names.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const skillDir = path.resolve(here, "..");

export function chartSkill() {
  const tries = [process.env.TS_CUSTOM_CHARTS_SKILL, ...["ts-custom-charts-builder", "thoughtspot-amuzing-chart"].map((n) => path.join(skillDir, "..", n))].filter(Boolean);
  for (const t of tries) if (fs.existsSync(path.join(t, "library", "_shared", "core.js"))) return fs.realpathSync(t);
  throw new Error("ts-custom-charts-builder skill not found next to " + skillDir + "; install it alongside, or set TS_CUSTOM_CHARTS_SKILL");
}
