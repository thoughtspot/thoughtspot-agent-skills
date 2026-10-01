// Runs ts-object-liveboard-chart-builder's sandbox code (scripts/patch.js, as packed by liveboard-pack.mjs) against a
// mock `ts` holding Liveboards the skill does not fully own, and checks that nothing it does not own is lost:
// the merge keeps the user's content, and every way of losing it the review found (a user's copy of a skill
// tile, a chart pinned from an answer, a failed search, an untabbed Liveboard, tiles from before owner markers,
// no backup, a loss on the server side) either keeps the content or refuses to commit.
// Called by smoke_ts_object_liveboard_chart_builder.py; prints one JSON line: { ok, failures, summary }.
//
//   node _liveboard_patch_mock.mjs <liveboard skill dir> <scratch dir>
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const [skill, scratch] = process.argv.slice(2);
const LB = "00000000-0000-0000-0000-00000000000b";
const OTHER_LB = "00000000-0000-0000-0000-00000000000d";
const TAB = "01 Test";
const END_JS = "/* ==== end amuzing core ==== */";
// The packer reads the user's library first; point it at an empty cache so only the shipped charts are used.
const cache = path.join(scratch, "xdg");
fs.mkdirSync(cache, { recursive: true });

// A spec with two library charts on one tab, and two filters.
const lbDir = path.join(scratch, "lb");
fs.mkdirSync(lbDir, { recursive: true });
const spec = {
  liveboard: { guid: LB, name: "Mock", description: "mock", model: { name: "Mock model", guid: "00000000-0000-0000-0000-0000000000c1" } },
  filters: [{ column: "region", label: "Region", applyToNarrative: false }, { column: "item type", label: "Item type" }],
  style: [{ name: "lb_border_type", value: "CURVED" }],
  tabs: [{ name: TAB, tiles: [
    { slug: "about-guide", title: "Guide", search: "[sales] [region]", x: 0, y: 0, w: 12, h: 4, filters: false },
    { slug: "banner-next", title: "Next", search: "[sales] [region]", x: 0, y: 4, w: 12, h: 3 }
  ] }]
};
fs.writeFileSync(path.join(lbDir, "liveboard.spec.json"), JSON.stringify(spec));
const backupFile = path.join(scratch, "backup.json"); // written below, once base() exists: a full export
const pack = (...extra) => execFileSync("node", [path.join(skill, "scripts", "liveboard-pack.mjs"), "--liveboard", lbDir, "--commit", "banner-next", ...extra],
  { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, XDG_CACHE_HOME: cache } });
const packFails = (...extra) => { try { pack(...extra); return false; } catch (e) { return e.status === 2; } };

// Tiles.
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");
const custom = (js) => JSON.stringify({ clientState: JSON.stringify({ version: 1, playground: { code: { jsCodeBase64: b64(js), cssCodeBase64: b64("/* ==== end amuzing core css ==== */"), htmlCodeBase64: b64("<div></div>") } } }) });
const jsOf = (x) => Buffer.from(JSON.parse(JSON.parse(x.answer.chart.custom_visual_props).clientState).playground.code.jsCodeBase64, "base64").toString();
const tile = (slug, owner) => custom("/* core */\n" + END_JS + "\n/* amuzing-slug: " + slug + " */\n" + (owner ? "/* ts-lb-owner: " + owner + " */\n" : "") + "render();");
const viz = (id, name, props) => ({ id, answer: { name, search_query: "[sales] [region]", chart: { type: "MUZE_STUDIO", custom_visual_props: props } } });
const native = { id: "Viz_1", answer: { name: "Native revenue", search_query: "[sales]", chart: { type: "COLUMN", axis_configs: [{ x: ["Region"], y: ["Total Sales"] }] } } };
const note = { id: "Viz_2", note_tile: { html_parsed_string: "<p>Keep me</p>" } };
const foreign = viz("Viz_5", "Someone else's custom chart", custom("plain();"));
const stale = viz("Viz_3", "Old chart", tile("old-chart", LB));
const guide = viz("Viz_4", "Guide", tile("about-guide", LB));
// A chart saved by the sibling answer skill and pinned here: it carries the core but no slug or owner marker.
const pinned = viz("Viz_7", "Pinned answer chart", custom("/* core */\n" + END_JS + "\nmine();"));
// The user's copy of the skill's guide tile, on a tab of their own: same slug and owner markers.
const copy = viz("Viz_6", "Guide (my copy)", tile("about-guide", LB));
// A tile from another Liveboard built by the skill, copied here.
const otherLb = viz("Viz_8", "From another Liveboard", tile("banner-next", OTHER_LB));

const base = () => JSON.parse(JSON.stringify({
  guid: LB,
  liveboard: {
    name: "The user's own name", description: "The user's description",
    visualizations: [native, note, foreign, stale, guide, pinned, copy, otherLb],
    parameters: [{ name: "Growth rate", data_type: "DOUBLE" }],
    filters: [
      { column: ["region"], oper: "in", values: ["West"], display_name: "Area", is_mandatory: true, excluded_visualizations: ["Viz_1"] },
      { column: ["year"], excluded_visualizations: ["Viz_3"] }
    ],
    ordered_chips: [{ name: "year", type: "FILTER" }],
    layout: { tabs: [
      { name: TAB, tiles: [
        { visualization_id: "Viz_4", x: 0, y: 0, width: 12, height: 4 },
        { visualization_id: "Viz_1", x: 0, y: 2, width: 6, height: 4 },
        { visualization_id: "Viz_3", x: 6, y: 8, width: 6, height: 4 }
      ] },
      { name: "Notes", tiles: [{ visualization_id: "Viz_2", x: 0, y: 0, width: 12, height: 2 }, { visualization_id: "Viz_5", x: 0, y: 2, width: 12, height: 4 }] },
      { name: "Mine", tiles: [{ visualization_id: "Viz_6", x: 0, y: 0, width: 12, height: 4 }, { visualization_id: "Viz_7", x: 0, y: 4, width: 6, height: 4 }, { visualization_id: "Viz_8", x: 6, y: 4, width: 6, height: 4 }] },
      { name: "Old tab", tiles: [] }
    ] },
    style: { style_properties: [{ name: "lb_border_type", value: "SQUARE" }, { name: "hide_group_title", value: "true" }] }
  }
}));

fs.writeFileSync(backupFile, JSON.stringify(base()));

// A mock cluster. `opts.search` fails searches, `opts.cols` sets the columns a search returns; `opts.lose` drops a
// visualization on import and `opts.mutate` edits what was imported (server-side changes); `opts.exportDown`
// fails every export after the commit.
function cluster(doc, opts = {}) {
  const st = { stored: JSON.parse(JSON.stringify(doc)), imports: [] };
  st.ts = {
    async post(url, body) {
      if (url.endsWith("/metadata/tml/export")) { if (opts.exportDown && st.imports.includes("ALL_OR_NONE")) throw new Error("socket hang up"); return { status: 200, body: [{ edoc: JSON.stringify(st.stored) }] }; }
      if (url.endsWith("/searchdata")) return opts.search === "fail" ? { status: 500, body: { error: "timeout" } } : { status: 200, body: { contents: [{ column_names: opts.cols || ["Region", "Total Sales"] }] } };
      if (url.endsWith("/metadata/tml/import")) {
        st.imports.push(body.import_policy);
        if (body.import_policy === "ALL_OR_NONE") {
          st.stored = JSON.parse(body.metadata_tmls[0]);
          if (opts.lose) st.stored.liveboard.visualizations = st.stored.liveboard.visualizations.filter((v) => v.id !== opts.lose);
          if (opts.mutate) opts.mutate(st.stored.liveboard);
        }
        return { status: 200, body: [{ response: { status: { status_code: "OK" } } }] };
      }
      throw new Error("unexpected call " + url);
    }
  };
  return st;
}
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
const run = async (block, doc, opts) => { const c = cluster(doc, opts); const summary = await new AsyncFunction("ts", block)(c.ts); return { ...c, summary }; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const has = (s, re) => (s.problems || []).some((p) => re.test(p.from));

const failures = [];
const expect = (cond, what) => { if (!cond) failures.push(what); };
const withBackup = pack("--backup", backupFile);

// 1. The merge, on a Liveboard full of things the skill does not own.
const m = await run(withBackup, base());
const after = m.stored.liveboard, summary = m.summary;
const v = (id) => after.visualizations.find((x) => x.id === id);
const tab = (n) => after.layout.tabs.find((t) => t.name === n);
expect(same(m.imports, ["VALIDATE_ONLY", "ALL_OR_NONE"]), "merge: validate then commit, once each");
expect(summary.roundTripAllOk === true, "merge: round trip passes");
for (const [x, what] of [[native, "native chart"], [note, "note"], [foreign, "custom chart without the core"], [pinned, "chart pinned from an answer (core, no owner)"], [copy, "the user's copy of a skill tile"], [otherLb, "a tile owned by another Liveboard"]]) expect(same(v(x.id), x), "merge: " + what + " kept verbatim");
expect(!v("Viz_3"), "merge: owned tile no longer in the spec removed");
expect(same(summary.removed, ["Old chart"]), "merge: only the dropped owned tile removed");
expect(v("Viz_4") && v("Viz_4").answer.name === "Guide", "merge: owned tile kept its visualization id");
expect(after.visualizations.length === 8, "merge: eight visualizations: six kept, two composed");
expect(same(after.parameters, base().liveboard.parameters), "merge: parameters kept");
expect(after.name === "The user's own name" && after.description === "The user's description", "merge: the Liveboard keeps its name and description");
const region = after.filters.find((f) => f.column[0] === "region");
expect(region && same(region.values, ["West"]) && region.display_name === "Area" && region.is_mandatory === true, "merge: the user's filter on a spec column keeps its values, label and mandatory flag");
expect(region && (region.excluded_visualizations || []).includes("Viz_1") && (region.excluded_visualizations || []).includes("Viz_4"), "merge: the user's exclusion kept, the spec's added");
const year = after.filters.find((f) => f.column[0] === "year");
expect(year && !("excluded_visualizations" in year), "merge: filter kept, pointer to the removed tile dropped");
expect(after.filters.some((f) => f.column[0] === "item type" && !("skip" in f)), "merge: a new spec filter added");
expect(after.ordered_chips.some((c) => c.name === "year") && after.ordered_chips.some((c) => c.name === "region"), "merge: chips kept and added");
expect(tab("Notes") && tab("Notes").tiles.length === 2 && tab("Mine") && tab("Mine").tiles.length === 3, "merge: tabs the spec does not name kept whole");
expect(tab("Old tab"), "merge: empty tab the user made kept");
const nat = tab(TAB) && tab(TAB).tiles.find((t) => t.visualization_id === "Viz_1");
expect(nat && nat.y >= 7, "merge: overlapping native tile moved below the charts");
const style = Object.fromEntries(after.style.style_properties.map((p) => [p.name, p.value]));
expect(style.lb_border_type === "CURVED" && style.hide_group_title === "true", "merge: style merged by name");
expect(same(summary.replaced, ["banner-next"]), "merge: only the sent chart replaced");
const next = tab(TAB) && tab(TAB).tiles.find((t) => t.y === 4);
expect(next && jsOf(v(next.visualization_id)).includes("/* ts-lb-owner: " + LB + " */"), "merge: composed tile carries this Liveboard's owner marker");

// 2. No backup: content the skill does not own is never written without one.
const nb = await run(pack(), base());
expect(/backup/.test(nb.summary.refused || "") && same(nb.imports, ["VALIDATE_ONLY"]) && same(nb.stored, base()), "no backup: commit refused, Liveboard unchanged");
expect(packFails("--backup", path.join(scratch, "nope.json")), "no backup: a missing backup file is refused by the packer");
const wrong = path.join(scratch, "wrong.json"); fs.writeFileSync(wrong, "{}");
expect(packFails("--backup", wrong), "no backup: a backup of another object is refused by the packer");

// 3. A failed search keeps the tile and refuses the commit.
const sf = await run(withBackup, base(), { search: "fail" });
expect(has(sf.summary, /SEARCH FAILED/) && /NOT COMMITTED/.test(sf.summary.refused || ""), "failed search: reported and the commit refused");
expect(same(sf.imports, ["VALIDATE_ONLY"]) && same(sf.stored, base()), "failed search: Liveboard unchanged");

// 4. An untabbed Liveboard is refused before anything is composed.
const flat = base(); flat.liveboard.layout = { tiles: flat.liveboard.layout.tabs.flatMap((t) => t.tiles) };
const un = await run(withBackup, flat);
expect(/without tabs/.test(un.summary.refused || "") && !un.imports.length && same(un.stored, flat), "untabbed: refused, nothing imported");

// 5. Two tiles marked with one slug on a spec tab, neither at its spec position: no telling which is the skill's.
const tie = base(); tie.liveboard.layout.tabs[0].tiles[0].x = 6;
tie.liveboard.layout.tabs[2].tiles = tie.liveboard.layout.tabs[2].tiles.filter((x) => x.visualization_id !== "Viz_6");
tie.liveboard.layout.tabs[0].tiles.push({ visualization_id: "Viz_6", x: 0, y: 20, width: 12, height: 4 });
const t5 = await run(withBackup, tie);
expect(has(t5.summary, /about-guide: 2 tiles/) && same(t5.stored, tie), "copy conflict: reported, Liveboard unchanged");

// 6. Tiles from before owner markers are taken over only with --adopt.
const old = base();
old.liveboard.visualizations = old.liveboard.visualizations.filter((x) => x.id !== "Viz_6").map((x) => (x.id === "Viz_4" ? viz("Viz_4", "Guide", tile("about-guide", null)) : x));
old.liveboard.layout.tabs[2].tiles = old.liveboard.layout.tabs[2].tiles.filter((x) => x.visualization_id !== "Viz_6");
const a1 = await run(withBackup, old);
expect(has(a1.summary, /no owner marker/) && same(a1.stored, old), "legacy tile: commit refused without --adopt");
const a2 = await run(pack("--backup", backupFile, "--adopt"), old);
const g2 = a2.stored.liveboard.visualizations.find((x) => x.id === "Viz_4");
expect(a2.summary.roundTripAllOk === true && same(a2.summary.marked, ["about-guide"]) && g2 && jsOf(g2).includes("ts-lb-owner: " + LB), "legacy tile: --adopt takes it over and marks it");

// 7. A loss on the server side fails the round trip.
const lo = await run(withBackup, base(), { lose: "Viz_2" });
expect(lo.summary.roundTripAllOk === false && (lo.summary.roundTripLost || []).length === 1, "server-side loss: the round trip fails and names it");

// 8. A search that returns no columns is a failed search, not a tile with no columns.
const ec = await run(withBackup, base(), { cols: [] });
expect(has(ec.summary, /SEARCH FAILED/) && same(ec.imports, ["VALIDATE_ONLY"]) && same(ec.stored, base()), "empty columns: refused, Liveboard unchanged");

// 9. A layout with both layout.tiles and tabs is refused (merging would orphan the untabbed tiles).
const mixed = base(); mixed.liveboard.layout.tiles = [{ visualization_id: "Viz_2", x: 0, y: 0, width: 6, height: 2 }];
const mx = await run(withBackup, mixed);
expect(/without tabs/.test(mx.summary.refused || "") && !mx.imports.length && same(mx.stored, mixed), "mixed layout: refused, nothing imported");

// 10. A marked tile on a tab the spec does not name is the user's, even when it is the only one of its slug.
const lone = base(); lone.liveboard.visualizations = lone.liveboard.visualizations.filter((x) => x.id !== "Viz_4");
lone.liveboard.layout.tabs[0].tiles = lone.liveboard.layout.tabs[0].tiles.filter((x) => x.visualization_id !== "Viz_4");
const ln = await run(pack("--backup", backupFile, "--max", "900000", "about-guide"), lone);
const lnAfter = ln.stored.liveboard;
expect(ln.summary.roundTripAllOk === true && same(lnAfter.visualizations.find((x) => x.id === "Viz_6"), copy) && lnAfter.layout.tabs.find((t) => t.name === "Mine").tiles.some((t) => t.visualization_id === "Viz_6"), "lone copy on the user's tab: kept verbatim in place, the spec tile built fresh");

// 11. Server-side changes to what the skill did not own fail the round trip.
for (const [what, mutate] of [
  ["parameters dropped", (l) => { delete l.parameters; }],
  ["a user filter changed", (l) => { l.filters.find((f) => f.column[0] === "region").values = ["East"]; }],
  ["Liveboard renamed", (l) => { l.name = "Renamed"; }],
  ["a native chart's settings changed", (l) => { l.visualizations.find((x) => x.id === "Viz_1").answer.chart.axis_configs = [{ x: ["Store"], y: ["Total Sales"] }]; }],
  ["a tab tile points at a missing visualization", (l) => { l.layout.tabs.find((t) => t.name === "Notes").tiles[0].visualization_id = "Viz_99"; }],
]) {
  const r = await run(withBackup, base(), { mutate });
  expect(r.summary.roundTripAllOk === false, "server-side change caught: " + what);
}

// 12. An export failure after the commit is reported, not thrown.
const ed = await run(withBackup, base(), { exportDown: true });
expect(ed.summary.roundTripAllOk === false && /commit landed/.test(ed.summary.roundTripError || ""), "export down after commit: reported, not thrown");

// 13. Backups that only look right.
const future = path.join(scratch, "future.json"); fs.writeFileSync(future, JSON.stringify(base())); fs.utimesSync(future, new Date("2099-01-01"), new Date("2099-01-01"));
expect(packFails("--backup", future), "backup: a future-dated file is refused");
const mention = path.join(scratch, "mention.json"); fs.writeFileSync(mention, JSON.stringify({ guid: OTHER_LB, liveboard: { description: "copied from " + LB } }));
expect(packFails("--backup", mention), "backup: another Liveboard that only mentions this guid is refused");
const repoDir = path.join(scratch, "repo"); fs.mkdirSync(path.join(repoDir, ".git"), { recursive: true });
fs.writeFileSync(path.join(repoDir, "b.json"), JSON.stringify(base()));
const link = path.join(scratch, "link.json"); fs.symlinkSync(path.join(repoDir, "b.json"), link);
expect(packFails("--backup", link), "backup: a symlink to a file inside a git tree is refused");
expect(packFails("--backup"), "--backup with no value exits 2");

// 14. Third review.
// A spec guid in upper case: the lower-case owner markers still match, nothing is doubled.
const upDir = path.join(scratch, "lb-upper"); fs.mkdirSync(upDir, { recursive: true });
fs.writeFileSync(path.join(upDir, "liveboard.spec.json"), JSON.stringify({ ...spec, liveboard: { ...spec.liveboard, guid: LB.toUpperCase() } }));
const upBlock = execFileSync("node", [path.join(skill, "scripts", "liveboard-pack.mjs"), "--liveboard", upDir, "--commit", "banner-next", "--backup", backupFile], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, XDG_CACHE_HOME: cache } });
const up = await run(upBlock, base());
expect(up.summary.roundTripAllOk === true && up.stored.liveboard.visualizations.length === 8 && same(up.summary.removed, ["Old chart"]), "guid case: upper-case spec guid matches lower-case markers, nothing doubled");

// An owned tile whose slug comment was removed, off its spec position: refused, not removed.
const noSlug = base();
noSlug.liveboard.visualizations.push(viz("Viz_9", "My edited chart", custom("/* core */\n" + END_JS + "\n/* ts-lb-owner: " + LB + " */\nedited();")));
noSlug.liveboard.layout.tabs[0].tiles.push({ visualization_id: "Viz_9", x: 0, y: 30, width: 6, height: 4 });
fs.writeFileSync(path.join(scratch, "backup-noslug.json"), JSON.stringify(noSlug));
const ns = await run(pack("--backup", path.join(scratch, "backup-noslug.json")), noSlug);
expect(has(ns.summary, /no slug marker/) && same(ns.stored, noSlug), "owned tile without slug off position: refused, Liveboard unchanged");

// --adopt does not take a tile matched only by position (it may be a pinned answer chart); --adopt-by-position does.
const byPos = base(); byPos.liveboard.visualizations = byPos.liveboard.visualizations.map((x) => (x.id === "Viz_4" ? viz("Viz_4", "Pinned at a spec position", custom("/* core */\n" + END_JS + "\nmine();")) : x));
const bp1 = await run(pack("--backup", backupFile, "--adopt"), byPos);
expect(has(bp1.summary, /matched by position only/) && same(bp1.stored, byPos), "adopt: a position-only match is refused under --adopt");
const bp2 = await run(pack("--backup", backupFile, "--adopt-by-position"), byPos);
expect(bp2.summary.roundTripAllOk === true && same(bp2.summary.marked, ["about-guide"]), "adopt: --adopt-by-position takes it over");

// Backups: a stub is refused by the packer, and a backup of an older state is refused by the sandbox.
const stub = path.join(scratch, "stub.json"); fs.writeFileSync(stub, JSON.stringify({ guid: LB, liveboard: {} }));
expect(packFails("--backup", stub), "backup: a stub with no visualizations is refused");
const yamlStub = path.join(scratch, "stub.tml"); fs.writeFileSync(yamlStub, "guid: " + LB + "\nliveboard:\n");
expect(packFails("--backup", yamlStub), "backup: a two-line YAML stub is refused");
const older = JSON.parse(JSON.stringify(base())); older.liveboard.visualizations = older.liveboard.visualizations.filter((x) => x.id !== "Viz_2");
const olderFile = path.join(scratch, "older.json"); fs.writeFileSync(olderFile, JSON.stringify(older));
const ob = await run(pack("--backup", olderFile), base());
expect(/not of this Liveboard as it is now/.test(ob.summary.refused || "") && same(ob.imports, ["VALIDATE_ONLY"]), "backup: a backup that lacks a current visualization is refused in the sandbox");
const yamlFull = path.join(scratch, "full.tml");
fs.writeFileSync(yamlFull, "guid: " + LB + "\nliveboard:\n  name: x\n  visualizations:\n" + base().liveboard.visualizations.map((v) => "  - id: " + v.id + "\n    answer:\n      name: n\n").join("") + "  layout:\n    tabs: []\n");
const yf = await run(pack("--backup", yamlFull), base());
expect(yf.summary.roundTripAllOk === true, "backup: a full YAML export is accepted");
const tampered = withBackup.replace(/"vizIds":\["Viz_1"/, '"vizIds":["Viz_X"');
const tb = await run(tampered, base());
expect(/CHECKSUM/.test(tb.summary.refused || "") && !tb.imports.length, "backup: an edited backup summary fails the checksum");

// What a live run on ps-internal showed ThoughtSpot doing on re-export: ids renumbered, six default style
// properties added, viz_guid and tab ids filled in. None of it is a loss.
const reexport = (l) => {
  const map = {}; l.visualizations.forEach((v, i) => { map[v.id] = "Viz_" + (i + 1); v.id = map[v.id]; v.viz_guid = "00000000-0000-0000-0000-0000000001" + String(i).padStart(2, "0"); });
  l.layout.tabs.forEach((t, i) => { t.id = "tab-" + i; t.tiles.forEach((x) => { x.visualization_id = map[x.visualization_id] || x.visualization_id; }); });
  l.filters.forEach((f) => { if (f.excluded_visualizations) f.excluded_visualizations = f.excluded_visualizations.map((id) => map[id] || id); });
  l.style.style_properties.push({ name: "lb_brand_color", value: "LBC_A" }, { name: "hide_group_description", value: "true" }, { name: "kpi_hero_font_size", value: "M" });
};
const rx = await run(withBackup, base(), { mutate: reexport });
expect(rx.summary.roundTripAllOk === true, "round trip: ThoughtSpot's re-export changes (renumbered ids, default style, viz_guid, tab ids) are not a loss");

// The round trip allows fields ThoughtSpot adds on re-export, and catches swaps, lost style and lost chips.
const dm = await run(withBackup, base(), { mutate: (l) => { l.visualizations.find((x) => x.id === "Viz_1").answer.display_mode = "CHART_MODE"; } });
expect(dm.summary.roundTripAllOk === true, "round trip: a default field added on re-export is not a loss");
for (const [what, mutate] of [
  ["user tiles swapped between tabs", (l) => { const n = l.layout.tabs.find((t) => t.name === "Notes"), m = l.layout.tabs.find((t) => t.name === "Mine"); const a = n.tiles[0].visualization_id; n.tiles[0].visualization_id = m.tiles[1].visualization_id; m.tiles[1].visualization_id = a; }],
  ["a user tile moved", (l) => { l.layout.tabs.find((t) => t.name === "Notes").tiles[1].y = 40; }],
  ["style lost", (l) => { delete l.style; }],
  ["ordered chips lost", (l) => { delete l.ordered_chips; }],
]) {
  const r = await run(withBackup, base(), { mutate });
  expect(r.summary.roundTripAllOk === false, "server-side change caught: " + what);
}

console.log(JSON.stringify({ ok: !failures.length, failures, summary }));
