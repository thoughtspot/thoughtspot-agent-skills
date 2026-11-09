#!/usr/bin/env node
// _liveboard_patch_mock.mjs — runs the blocks ts-object-liveboard-chart-builder's liveboard-pack.mjs prints
// against an in-memory ThoughtSpot: a mock `ts` answering the three REST calls scripts/patch.js makes (TML
// export, searchdata, TML import). Import renumbers visualization ids the way a cluster does, so the round trip
// is tested the way it runs live. Each scenario is a case the write path must get right; most come from review.
//
// Called by smoke_ts_object_liveboard_chart_builder.py. Prints one PASS/FAIL line per scenario, exits 1 on any FAIL.
// Needs only node; the user's chart library (~/.cache/ts-charts) is kept out by a temporary XDG_CACHE_HOME.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PACK = path.join(ROOT, "agents", "cli", "ts-object-liveboard-chart-builder", "scripts", "liveboard-pack.mjs");
const CREATE = path.join(ROOT, "agents", "cli", "ts-object-liveboard-chart-builder", "scripts", "mcp", "create-liveboard.js");
const BLOCK = path.join(ROOT, "agents", "cli", "ts-object-answer-chart-builder", "helpers", "mcp-block.mjs");
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "lb-patch-mock-"));
const ENV = { ...process.env, XDG_CACHE_HOME: path.join(TMP, "cache") };
const LBG = "11111111-2222-4333-8444-555555555555", OTHER = "99999999-2222-4333-8444-555555555555";
const MODEL = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const AsyncFunction = (async () => {}).constructor;
const clone = (x) => JSON.parse(JSON.stringify(x));

const DIR = path.join(TMP, "lb");
fs.mkdirSync(DIR, { recursive: true });
fs.writeFileSync(path.join(DIR, "liveboard.spec.json"), JSON.stringify({
  liveboard: { guid: LBG, name: "Mock", description: "", model: { name: "M", guid: MODEL } },
  filters: [{ column: "region", label: "Region" }],
  style: [{ name: "lb_border_type", value: "CURVED" }],
  tabs: [{ name: "T1", tiles: [
    { slug: "pulse-kpi-best", title: "Best", search: "[sales] [region]", x: 0, y: 0, w: 6, h: 4 },
    { slug: "where-state-bubbles", title: "Bubbles", search: "[sales] [state]", x: 6, y: 0, w: 6, h: 4 },
    { slug: "banner-pulse", title: "About", search: "[sales] [date].monthly", x: 0, y: 4, w: 12, h: 3 }
  ] }]
}));

function pack(args) {
  const p = spawnSync("node", [PACK, "--liveboard", DIR, ...args], { encoding: "utf8", env: ENV, maxBuffer: 64 << 20 });
  return { code: p.status, blocks: p.stdout.split(/^=====$/m).map((b) => b.trim()).filter(Boolean), err: p.stderr };
}
function backup(doc, name = "b.json") {
  const d = path.join(TMP, "backups"); fs.mkdirSync(d, { recursive: true });
  const f = path.join(d, name);
  fs.writeFileSync(f, JSON.stringify(doc === undefined ? null : [{ edoc: JSON.stringify(doc) }]));
  return f;
}
const cols = (q) => [...q.matchAll(/\[([^\]]+)\]/g)].map((m) => (m[1] === "sales" ? "Total Sales" : m[1][0].toUpperCase() + m[1].slice(1)));
// ThoughtSpot renumbers visualization ids on import (seen live): Viz_1, Viz_2 ... in document order.
function renumber(doc) {
  const lb = doc.liveboard, map = {};
  (lb.visualizations || []).forEach((v, i) => { map[v.id] = "Viz_" + (i + 1); v.id = map[v.id]; });
  for (const t of (lb.layout && lb.layout.tabs) || []) for (const x of t.tiles || []) x.visualization_id = map[x.visualization_id];
  for (const f of lb.filters || []) if (f.excluded_visualizations) f.excluded_visualizations = f.excluded_visualizations.map((id) => map[id]);
  return doc;
}
function mockTs(state, onExport) {
  let n = 0;
  return { post: async (p, body) => {
    if (p.endsWith("/metadata/tml/export")) {
      n++; if (onExport) onExport(n, state);
      const id = String(body.metadata[0].identifier).toLowerCase();
      // A cluster's export holds table fqns only when export_fqn is asked for; the mock does the same.
      const out = body.export_fqn ? state.doc : JSON.parse(JSON.stringify(state.doc || null, (k, v) => (k === "fqn" ? undefined : v)));
      return state.doc && id === LBG ? { status: 200, body: [{ edoc: JSON.stringify(out) }] } : { status: 400, body: { error: "not found" } };
    }
    if (p.endsWith("/searchdata")) return { status: 200, body: { contents: [{ column_names: /FAIL/.test(body.query_string) ? [] : cols(body.query_string) }] } };
    if (p.endsWith("/metadata/tml/import")) {
      const doc = JSON.parse(body.metadata_tmls[0]);
      if (body.import_policy === "ALL_OR_NONE") { state.doc = renumber(doc); state.commits = (state.commits || 0) + 1; }
      return { status: 200, body: [{ response: { status: { status_code: "OK" }, header: { id_guid: doc.guid } } }] };
    }
    throw new Error("mock ts: unexpected call " + p);
  } };
}
const run = (block, state, onExport) => new AsyncFunction("ts", block)(mockTs(state, onExport));
const tabOf = (doc) => doc.liveboard.layout.tabs.find((t) => t.name === "T1");
const vizNamed = (doc, n) => doc.liveboard.visualizations.find((v) => v.answer && v.answer.name === n);
const placeOf = (doc, n) => { const v = vizNamed(doc, n); const t = v && tabOf(doc).tiles.find((x) => x.visualization_id === v.id); return t ? t.x + "," + t.y : null; };
const jsOf = (v) => Buffer.from(JSON.parse(JSON.parse(v.answer.chart.custom_visual_props).clientState).playground.code.jsCodeBase64, "base64").toString("utf8");
const withViz = (doc, viz, x, y, w = 6, h = 4) => { doc.liveboard.visualizations.push(viz); tabOf(doc).tiles.push({ visualization_id: viz.id, x, y, width: w, height: h }); return doc; };
const cvp = (js) => JSON.stringify({ clientState: JSON.stringify({ version: 1, playground: { version: "v1", code: { jsCodeBase64: Buffer.from(js).toString("base64"), cssCodeBase64: "", htmlCodeBase64: "" } } }) });

const results = [];
async function scenario(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name + ": " + (e && e.message || e)]); }
}
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };
const committed = (r) => ok(r && r.import && r.import.status_code === "OK" && r.roundTripAllOk === true && !(r.problems || []).length, "not a clean commit: " + JSON.stringify(r).slice(0, 600));
const refused = (r, re) => ok(r && r.refused && re.test(r.refused + JSON.stringify(r.problems || [])), "expected a refusal matching " + re + ", got " + JSON.stringify(r).slice(0, 600));

await scenario("Step 3 creates the Liveboard with its tabs, validating first, and refuses on a failed validate", async () => {
  const p = spawnSync("node", [BLOCK, CREATE, "--name", "Mock", "--description", "d", "--tabs", "01 About,02 Where"], { encoding: "utf8", env: ENV });
  ok(p.status === 0, "mcp-block: " + p.stderr);
  const calls = [];
  const ts = (fail) => ({ post: async (u, body) => { calls.push(body.import_policy); const doc = JSON.parse(body.metadata_tmls[0]);
    ok(doc.liveboard.layout.tabs.map((t) => t.name).join() === "01 About,02 Where", "tabs " + JSON.stringify(doc.liveboard.layout.tabs));
    return { status: 200, body: [{ response: { status: { status_code: fail && body.import_policy === "VALIDATE_ONLY" ? "ERROR" : "OK" }, header: { id_guid: LBG } } }] }; } });
  const r = await new AsyncFunction("ts", p.stdout)(ts(false));
  ok(r.guid === LBG && calls.join() === "VALIDATE_ONLY,ALL_OR_NONE", JSON.stringify(r) + " " + calls);
  calls.length = 0;
  const bad = await new AsyncFunction("ts", p.stdout)(ts(true));
  ok(bad.refused && calls.join() === "VALIDATE_ONLY", "an import followed a failed validate");
});

let base = null;
const empty = () => ({ guid: LBG, liveboard: { name: "Mock", visualizations: [], layout: { tabs: [] } } });
const native = { id: "Viz_native", answer: { name: "Native", search_query: "[sales] [region]", description: "a user's chart", chart: { type: "COLUMN" }, display_mode: "CHART_MODE" } };
const note = { id: "Viz_note", note_tile: { html_parsed_string: "<p>user note</p>" } };

await scenario("a new, empty Liveboard is built in one commit and round-trips", async () => {
  const p = pack(["--commit", "--all"]); ok(p.code === 0 && p.blocks.length, "pack: " + p.err);
  const st = { doc: empty() }, replaced = [];
  for (const b of p.blocks) { const r = await run(b, st); committed(r); replaced.push(...r.replaced); }
  ok(replaced.length === 3, "replaced " + replaced);
  base = st.doc;
});

await scenario("a block keeps the skill's other tiles as they are, without searching them again", async () => {
  // Found live on ps-internal 26.11: an export without export_fqn has no table fqn, so every kept tile was rebuilt
  // from a new search, resetting anything the user set on it.
  const st = { doc: clone(base) };
  vizNamed(st.doc, "Bubbles").answer.table.client_state = "set by the user";
  const r = await run(pack(["--commit", "--backup", backup(st.doc), "pulse-kpi-best"]).blocks[0], st);
  committed(r);
  ok(r.searches === 1, "searched " + r.searches + " times for a one-chart block");
  ok(vizNamed(st.doc, "Bubbles").answer.table.client_state === "set by the user", "a kept tile's answer was rebuilt");
});

await scenario("B1: a native chart and a note on a spec tab do not crash validate, check or commit", async () => {
  const st = { doc: withViz(withViz(clone(base), clone(native), 0, 20), clone(note), 6, 20) };
  for (const mode of ["--validate", "--check"]) { const p = pack([mode, "pulse-kpi-best"]); const r = await run(p.blocks[0], { doc: clone(st.doc) }); ok(!r.refused || mode === "--check", mode + ": " + JSON.stringify(r).slice(0, 300)); }
  const p = pack(["--commit", "--backup", backup(st.doc), "--all"]);
  for (const b of p.blocks) committed(await run(b, st));
  ok(vizNamed(st.doc, "Native") && st.doc.liveboard.visualizations.some((v) => v.note_tile), "native chart or note lost");
});

await scenario("B2: a Liveboard with visualizations is not written without a backup", async () => {
  const st = { doc: clone(base) };
  refused(await run(pack(["--commit", "pulse-kpi-best"]).blocks[0], st), /export a backup/);
  ok(st.commits === undefined, "a commit landed");
});

await scenario("B2: a stub backup (ids only), an older export and another Liveboard's export are refused", async () => {
  const doc = withViz(clone(base), clone(native), 0, 20);
  // ids only: passes the disk check (it names the guid and lists visualizations) but holds no content
  const stub = { guid: LBG, liveboard: { visualizations: doc.liveboard.visualizations.map((v) => ({ id: v.id })) } };
  const st = { doc: clone(doc) };
  refused(await run(pack(["--commit", "--backup", backup(stub, "stub.json"), "pulse-kpi-best"]).blocks[0], st), /is not of this Liveboard/);
  // an older export: the native chart's search has changed since
  const older = clone(doc); vizNamed(older, "Native").answer.search_query = "[sales]";
  refused(await run(pack(["--commit", "--backup", backup(older, "older.json"), "pulse-kpi-best"]).blocks[0], st), /is not of this Liveboard/);
  // an older export that differs only in a description or an axis setting
  const olderDesc = clone(doc); vizNamed(olderDesc, "Native").answer.description = "before the edit";
  refused(await run(pack(["--commit", "--backup", backup(olderDesc, "older-desc.json"), "pulse-kpi-best"]).blocks[0], st), /is not of this Liveboard/);
  const olderAxis = clone(doc); vizNamed(olderAxis, "Native").answer.chart.axis_configs = [{ x: ["old"] }];
  refused(await run(pack(["--commit", "--backup", backup(olderAxis, "older-axis.json"), "pulse-kpi-best"]).blocks[0], st), /is not of this Liveboard/);
  // ids and viz_guids are renumbered on import, so a backup that differs only in them is current
  const renum = clone(doc); renum.liveboard.visualizations.forEach((v, i) => { v.id = "Viz_r" + i; v.viz_guid = "00000000-0000-4000-8000-00000000000" + i; });
  ok(!/is not of this Liveboard/.test(String((await run(pack(["--validate", "--backup", backup(renum, "renum.json"), "pulse-kpi-best"]).blocks[0], clone(st))).commitWouldRefuse || "")), "a backup differing only in ids was refused");
  // another Liveboard's export with the guid edited to this one
  const other = { guid: LBG, liveboard: { visualizations: [{ id: "Viz_1", answer: { name: "Other", search_query: "[x]", chart: { type: "COLUMN" } } }] } };
  refused(await run(pack(["--commit", "--backup", backup(other, "other.json"), "pulse-kpi-best"]).blocks[0], st), /is not of this Liveboard/);
  ok(st.commits === undefined, "a commit landed");
  // on disk: another guid, a cut-off file
  ok(pack(["--commit", "--backup", backup({ ...doc, guid: OTHER }, "g.json"), "pulse-kpi-best"]).code === 2, "a backup of another guid passed the disk check");
  const cut = path.join(TMP, "backups", "cut.json"); fs.writeFileSync(cut, JSON.stringify([{ edoc: JSON.stringify(doc) }]).slice(0, 400));
  ok(pack(["--commit", "--backup", cut, "pulse-kpi-best"]).code === 2, "a cut-off backup passed the disk check");
});

await scenario("B2: the Liveboard's own style is kept, the spec's only fills in what is missing", async () => {
  const doc = clone(base);
  doc.liveboard.style = { style_properties: [{ name: "lb_border_type", value: "FLAT" }, { name: "hide_tile_description", value: "true" }] };
  const st = { doc };
  committed(await run(pack(["--commit", "--backup", backup(doc), "pulse-kpi-best"]).blocks[0], st));
  const sp = st.doc.liveboard.style.style_properties;
  ok(sp.find((x) => x.name === "lb_border_type").value === "FLAT" && sp.find((x) => x.name === "hide_tile_description").value === "true", "style reset: " + JSON.stringify(sp));
});

await scenario("B2: a lone marked tile off its spec position (a user's copy) is not taken without --relayout", async () => {
  const doc = clone(base);
  tabOf(doc).tiles.find((x) => x.visualization_id === vizNamed(doc, "Best").id).y = 30;
  vizNamed(doc, "Best").answer.name = "My copy of Best";
  const st = { doc: clone(doc) };
  refused(await run(pack(["--commit", "--backup", backup(doc), "pulse-kpi-best"]).blocks[0], st), /not at its spec position/);
  ok(st.commits === undefined, "a commit landed");
  const st2 = { doc: clone(doc) };
  committed(await run(pack(["--commit", "--relayout", "--backup", backup(doc), "pulse-kpi-best"]).blocks[0], st2));
  ok(placeOf(st2.doc, "Best") === "0,0", "with --relayout the tile is at " + placeOf(st2.doc, "Best"));
});

await scenario("B2: --adopt leaves a user's chart with a copied slug marker alone, in a block for another slug", async () => {
  // The skill's own Bubbles tile is gone; the user's chart carries its slug marker (copied code) and sits elsewhere.
  const doc = clone(base), bub = vizNamed(doc, "Bubbles").id;
  doc.liveboard.visualizations = doc.liveboard.visualizations.filter((v) => v.id !== bub);
  tabOf(doc).tiles = tabOf(doc).tiles.filter((x) => x.visualization_id !== bub);
  const mine = { id: "Viz_user", answer: { name: "User lean chart", search_query: "[sales] [state]", chart: { type: "MUZE_STUDIO", custom_visual_props: cvp("/* amuzing-slug: where-state-bubbles */\nconsole.log(1);") } } };
  withViz(doc, mine, 0, 40);
  const st = { doc };
  // The block carries where-state-bubbles too, so it commits: the user's chart must not be what it builds on.
  const r = await run(pack(["--commit", "--adopt", "--backup", backup(doc), "pulse-kpi-best", "where-state-bubbles"]).blocks[0], st);
  committed(r);
  const back = vizNamed(st.doc, "User lean chart");
  ok(back && placeOf(st.doc, "User lean chart") === "0,40" && jsOf(back) === "/* amuzing-slug: where-state-bubbles */\nconsole.log(1);", "the user's chart was moved or rebuilt: " + JSON.stringify(r).slice(0, 300));
});

await scenario("B2: an edit made while the block runs (a tile's description) refuses the commit", async () => {
  const doc = withViz(clone(base), clone(native), 0, 20);
  const st = { doc };
  const r = await run(pack(["--commit", "--backup", backup(doc), "pulse-kpi-best"]).blocks[0], st, (n, s) => { if (n === 2) vizNamed(s.doc, "Native").answer.description = "edited meanwhile"; });
  ok(r.recheck === "changed", "recheck " + r.recheck);
  refused(r, /changed during the patch/);
  ok(vizNamed(st.doc, "Native").answer.description === "edited meanwhile", "the edit was overwritten");
});

await scenario("a later block pasted on its own still needs a backup, and keeps a user's marked copy", async () => {
  // A user's copy of a skill tile whose slug is not in this run's earlier blocks: only a backup may cover it.
  const doc = clone(base), best = vizNamed(doc, "Best");
  const copy = { ...clone(best), id: "Viz_copy", answer: { ...clone(best.answer), name: "Copy of Best" } };
  withViz(doc, copy, 0, 30);
  const p = pack(["--commit", "--max", "3000", "--all"]);
  ok(p.blocks.length === 3, "expected 3 blocks, got " + p.blocks.length);
  const st = { doc: clone(doc) };
  refused(await run(p.blocks[1], st), /export a backup/);
  refused(await run(p.blocks[2], st), /export a backup/);
  ok(st.commits === undefined, "a later block committed without a backup");
});

await scenario("a backup saved with ts tml export --parse is accepted, and fingerprinted", async () => {
  const doc = withViz(clone(base), clone(native), 0, 20), f = path.join(TMP, "backups", "parsed.json");
  fs.writeFileSync(f, JSON.stringify([{ type: "liveboard", guid: LBG, tml: { liveboard: doc.liveboard }, info: {} }]));
  const st = { doc: clone(doc) };
  committed(await run(pack(["--commit", "--backup", f, "pulse-kpi-best"]).blocks[0], st));
  ok(vizNamed(st.doc, "Native"), "native chart lost");
  // the same shape holding an older state is refused like any other older export
  const older = clone(doc); vizNamed(older, "Native").answer.description = "before the edit";
  const g = path.join(TMP, "backups", "parsed-older.json");
  fs.writeFileSync(g, JSON.stringify([{ type: "liveboard", guid: LBG, tml: { liveboard: older.liveboard }, info: {} }]));
  refused(await run(pack(["--commit", "--backup", g, "pulse-kpi-best"]).blocks[0], { doc: clone(doc) }), /is not of this Liveboard/);
});

await scenario("--validate warns that a commit would refuse for want of a backup", async () => {
  const r = await run(pack(["--validate", "pulse-kpi-best"]).blocks[0], { doc: clone(base) });
  ok(r.validate && r.validate.status_code === "OK" && /export a backup/.test(r.commitWouldRefuse || ""), JSON.stringify(r).slice(0, 300));
});

await scenario("a multi-block commit run passes with one backup taken before it", async () => {
  const doc = withViz(clone(base), clone(native), 0, 20);
  const p = pack(["--commit", "--max", "3000", "--backup", backup(doc), "--all"]);
  ok(p.blocks.length === 3, "expected 3 blocks, got " + p.blocks.length);
  const st = { doc };
  for (const b of p.blocks) committed(await run(b, st));
  ok(vizNamed(st.doc, "Native"), "native chart lost");
});

fs.rmSync(TMP, { recursive: true, force: true });
for (const [s, m] of results) console.log(s + " " + m);
process.exit(results.some(([s]) => s === "FAIL") ? 1 : 0);
