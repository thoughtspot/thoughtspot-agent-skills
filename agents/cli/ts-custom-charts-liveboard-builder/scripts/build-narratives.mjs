#!/usr/bin/env node
// Generates a Liveboard's narrative tiles (tab banners, About hero, guide) from this skill's
// narratives/render.{js,css} and one <liveboard dir>/narratives/<slug>.cfg.js per tile, into the chart
// skill's library/<slug>/chart.{html,css,js}, then syncs the shared core.
//   node scripts/build-narratives.mjs [--liveboard <dir>]   (default liveboards/amuzing-chart-samples)
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { chartSkill, skillDir } from './chart-skill.mjs';

const chart = chartSkill();
const lib = path.join(chart, 'library');
const li = process.argv.indexOf('--liveboard');
const lbDir = path.resolve(li >= 0 ? process.argv[li + 1] : path.join(skillDir, 'liveboards', 'amuzing-chart-samples'));
const nar = path.join(lbDir, 'narratives');
const render = fs.readFileSync(path.join(skillDir, 'narratives', 'render.js'), 'utf8');
const css = fs.readFileSync(path.join(skillDir, 'narratives', 'render.css'), 'utf8');
const HTML = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&display=swap">\n<div id="chart"></div>\n';
const CORE_JS = '/* ==== amuzing core v1 | placeholder, replaced by helpers/sync-core.mjs ==== */\n/* ==== end amuzing core ==== */\n\n';
const CORE_CSS = '/* ==== amuzing core css v1 | placeholder, replaced by helpers/sync-core.mjs ==== */\n/* ==== end amuzing core css ==== */\n\n';

const made = [];
for (const f of fs.readdirSync(nar).filter((n) => n.endsWith('.cfg.js'))) {
  const slug = f.replace('.cfg.js', '');
  const cfg = fs.readFileSync(path.join(nar, f), 'utf8').trim();
  const dir = path.join(lib, slug);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, '.uses-core'), '');
  fs.writeFileSync(path.join(dir, '.narrative'), '');
  fs.writeFileSync(path.join(dir, 'chart.html'), HTML);
  fs.writeFileSync(path.join(dir, 'chart.css'), CORE_CSS + css);
  fs.writeFileSync(path.join(dir, 'chart.js'), CORE_JS + render.replace('// __CFG__', () => cfg));
  made.push(slug);
}
execFileSync('node', [path.join(chart, 'helpers', 'sync-core.mjs'), ...made.map((s) => path.join(lib, s))], { stdio: 'inherit' });
console.log('generated: ' + made.join(', '));
