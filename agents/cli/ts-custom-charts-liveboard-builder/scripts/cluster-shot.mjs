#!/usr/bin/env node
// The in-cluster screenshot lives in the ts-custom-charts-builder skill (helpers/cluster-shot.mjs), which uses it
// for saved answers too. This keeps `node <L>/scripts/cluster-shot.mjs ...` working; the arguments pass through.
import path from "node:path";
import { pathToFileURL } from "node:url";
import { chartSkill } from "./chart-skill.mjs";

await import(pathToFileURL(path.join(chartSkill(), "helpers", "cluster-shot.mjs")).href);
