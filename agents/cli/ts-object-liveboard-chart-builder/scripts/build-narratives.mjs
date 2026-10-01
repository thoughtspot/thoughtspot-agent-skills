#!/usr/bin/env node
// Generates a Liveboard's narrative tiles (tab banners, About hero, guide) from this skill's
// narratives/render.{js,css} and one <liveboard dir>/narratives/<slug>.cfg.js per tile, into the user's chart
// library (~/.cache/ts-charts/library/<slug>/chart.{html,css,js}, outside any repo), then syncs the shared core.
//   node scripts/build-narratives.mjs [--liveboard <dir>] [--into-skill]   (default liveboards/amuzing-chart-samples)
// --into-skill writes into the chart skill's shipped library/ instead (maintainers of the worked example).
// Each <slug>/.narrative records the Liveboard folder that owns it. A slug owned by another Liveboard, in either
// library, is refused, so a new Liveboard cannot overwrite another's About or banners: give them their own slugs.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { chartSkill, skillDir } from './chart-skill.mjs';

const chart = chartSkill();
const { userLibrary } = await import(pathToFileURL(path.join(chart, 'helpers', 'env.mjs')).href);
const shipped = path.join(chart, 'library');
const lib = process.argv.includes('--into-skill') ? shipped : userLibrary();
const li = process.argv.indexOf('--liveboard');
const lbDir = path.resolve(li >= 0 ? process.argv[li + 1] : path.join(skillDir, 'liveboards', 'amuzing-chart-samples'));
const nar = path.join(lbDir, 'narratives');
const render = fs.readFileSync(path.join(skillDir, 'narratives', 'render.js'), 'utf8');
const css = fs.readFileSync(path.join(skillDir, 'narratives', 'render.css'), 'utf8');
const HTML = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&display=swap">\n<div id="chart"></div>\n';
const CORE_JS = '/* ==== amuzing core v1 | placeholder, replaced by helpers/sync-core.mjs ==== */\n/* ==== end amuzing core ==== */\n\n';
const CORE_CSS = '/* ==== amuzing core css v1 | placeholder, replaced by helpers/sync-core.mjs ==== */\n/* ==== end amuzing core css ==== */\n\n';

const owner = path.basename(lbDir);
const cfgs = fs.readdirSync(nar).filter((n) => n.endsWith('.cfg.js'));
const clash = [];
for (const f of cfgs) {
  const slug = f.replace('.cfg.js', '');
  for (const dir of [...new Set([path.join(lib, slug), path.join(shipped, slug)])]) {
    const mark = path.join(dir, '.narrative');
    const had = fs.existsSync(mark) ? fs.readFileSync(mark, 'utf8').trim() || 'amuzing-chart-samples' : null;
    if ((had && had !== owner) || (!had && fs.existsSync(path.join(dir, 'chart.js')))) { clash.push(slug + ' (owned by ' + (had || 'a library chart') + ')'); break; }
  }
}
if (clash.length) { console.error('refused, these slugs belong to something else: ' + clash.join(', ') + '. Rename the .cfg.js files, e.g. <liveboard>-banner-where.'); process.exit(2); }
const made = [];
for (const f of cfgs) {
  const slug = f.replace('.cfg.js', '');
  const cfg = fs.readFileSync(path.join(nar, f), 'utf8').trim();
  const dir = path.join(lib, slug);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, '.uses-core'), '');
  fs.writeFileSync(path.join(dir, '.narrative'), owner + '\n');
  fs.writeFileSync(path.join(dir, 'chart.html'), HTML);
  fs.writeFileSync(path.join(dir, 'chart.css'), CORE_CSS + css);
  fs.writeFileSync(path.join(dir, 'chart.js'), CORE_JS + render.replace('// __CFG__', () => cfg));
  made.push(slug);
}
execFileSync('node', [path.join(chart, 'helpers', 'sync-core.mjs'), ...made.map((s) => path.join(lib, s))], { stdio: 'inherit' });
console.log('generated in ' + lib + ': ' + made.join(', '));
