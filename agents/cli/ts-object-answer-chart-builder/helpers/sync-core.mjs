#!/usr/bin/env node
// Keeps the shared core block identical in every library chart.
//
//   node helpers/sync-core.mjs                 sync every chart under library/ and runs/*/chart
//   node helpers/sync-core.mjs <dir> [<dir>]   sync only these chart folders
//   node helpers/sync-core.mjs --check         report drift, change nothing (exit 1 on drift)
//
// A chart opts in by containing the marker pair
//   /* ==== amuzing core v1 ... */  ...  /* ==== end amuzing core ==== */      (chart.js)
//   /* ==== amuzing core css v1 ... */ ... /* ==== end amuzing core css ==== */ (chart.css)
// Files without markers are left alone unless the folder contains a `.uses-core` file,
// in which case the block is inserted at the top.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { cacheRoot, userLibrary } from './env.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const skill = path.resolve(here, '..');
const home = process.env.TS_CHART_HOME || cacheRoot();
const shared = path.join(skill, 'library', '_shared');

const args = process.argv.slice(2);
const check = args.includes('--check');
const dirs = args.filter((a) => !a.startsWith('--')).map((d) => path.resolve(d));

const kinds = [
  { file: 'chart.js', src: 'core.js', open: /\/\* ==== amuzing core v\d+[^\n]*\*\//, close: '/* ==== end amuzing core ==== */' },
  { file: 'chart.css', src: 'core.css', open: /\/\* ==== amuzing core css v\d+[^\n]*\*\//, close: '/* ==== end amuzing core css ==== */' },
];

function targets() {
  if (dirs.length) return dirs;
  const out = [];
  const lib = path.join(skill, 'library');
  for (const l of [lib, userLibrary()]) if (fs.existsSync(l)) for (const d of fs.readdirSync(l)) if (!d.startsWith('_')) out.push(path.join(l, d));
  const runs = path.join(home, 'runs');
  if (fs.existsSync(runs)) for (const d of fs.readdirSync(runs)) out.push(path.join(runs, d, 'chart'));
  return out.filter((d) => fs.existsSync(d) && fs.statSync(d).isDirectory());
}

let drift = 0, changed = 0;
for (const dir of targets()) {
  for (const k of kinds) {
    const f = path.join(dir, k.file);
    if (!fs.existsSync(f)) {
      if (!fs.existsSync(path.join(dir, '.uses-core'))) continue;
      if (!check) { fs.writeFileSync(f, ''); }
      else continue;
    }
    const block = fs.readFileSync(path.join(shared, k.src), 'utf8').replace(/\s+$/, '');
    let txt = fs.readFileSync(f, 'utf8');
    const m = k.open.exec(txt);
    let next;
    if (m) {
      const end = txt.indexOf(k.close, m.index);
      if (end < 0) { console.error('unterminated core block: ' + f); process.exitCode = 1; continue; }
      next = txt.slice(0, m.index) + block + txt.slice(end + k.close.length);
    } else if (fs.existsSync(path.join(dir, '.uses-core'))) {
      next = block + '\n\n' + txt;
    } else continue;
    if (next === txt) continue;
    drift++;
    if (!check) { fs.writeFileSync(f, next); changed++; console.log('synced ' + path.relative(home, f)); }
    else console.log('drift  ' + path.relative(home, f));
  }
}
console.log(check ? (drift ? drift + ' file(s) drifted' : 'core in sync') : changed + ' file(s) updated');
if (check && drift) process.exitCode = 1;
