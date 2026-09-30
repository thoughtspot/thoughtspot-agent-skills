// Runs ts-object-liveboard-builder's sandbox code (scripts/patch.js, as packed by liveboard-pack.mjs) against a
// mock `ts` holding a Liveboard the skill does not fully own, and checks the merge keeps everything it does not
// own. Called by smoke_ts_object_liveboard_builder.py; prints one JSON line: { ok, failures, summary }.
//
//   node _liveboard_patch_mock.mjs <liveboard skill dir> <scratch dir>
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const [skill, scratch] = process.argv.slice(2);
const LB = "00000000-0000-0000-0000-00000000000b";
const TAB = "01 Test";
const END_JS = "/* ==== end amuzing core ==== */";

// A spec with two library charts on one tab, and a Region filter.
const lbDir = path.join(scratch, "lb");
fs.mkdirSync(lbDir, { recursive: true });
const spec = {
  liveboard: { guid: LB, name: "Mock", description: "mock", model: { name: "Mock model", guid: "00000000-0000-0000-0000-0000000000c1" } },
  filters: [{ column: "region", label: "Region", applyToNarrative: false }],
  style: [{ name: "lb_border_type", value: "CURVED" }],
  tabs: [{ name: TAB, tiles: [
    { slug: "about-guide", title: "Guide", search: "[sales] [region]", x: 0, y: 0, w: 12, h: 4, filters: false },
    { slug: "banner-next", title: "Next", search: "[sales] [region]", x: 0, y: 4, w: 12, h: 3 }
  ] }]
};
fs.writeFileSync(path.join(lbDir, "liveboard.spec.json"), JSON.stringify(spec));
const block = execFileSync("node", [path.join(skill, "scripts", "liveboard-pack.mjs"), "--liveboard", lbDir, "--commit", "banner-next"],
  { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });

// What is on the Liveboard before the patch.
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");
const custom = (js) => JSON.stringify({ clientState: JSON.stringify({ version: 1, playground: { code: { jsCodeBase64: b64(js), cssCodeBase64: b64("/* ==== end amuzing core css ==== */"), htmlCodeBase64: b64("<div></div>") } } }) });
const owned = (slug) => custom("/* core */\n" + END_JS + "\n/* amuzing-slug: " + slug + " */\nrender();");
const native = { id: "Viz_1", answer: { name: "Native revenue", search_query: "[sales]", chart: { type: "COLUMN" } } };
const note = { id: "Viz_2", note_tile: { html_parsed_string: "<p>Keep me</p>" } };
const foreign = { id: "Viz_5", answer: { name: "Someone else's custom chart", chart: { type: "MUZE_STUDIO", custom_visual_props: custom("plain();") } } };
const stale = { id: "Viz_3", answer: { name: "Old chart", chart: { type: "MUZE_STUDIO", custom_visual_props: owned("old-chart") } } };
const guide = { id: "Viz_4", answer: { name: "Guide", chart: { type: "MUZE_STUDIO", custom_visual_props: owned("about-guide") } } };
const before = {
  guid: LB,
  liveboard: {
    name: "Mock", visualizations: [native, note, foreign, stale, guide],
    parameters: [{ name: "Growth rate", data_type: "DOUBLE" }],
    filters: [
      { column: ["region"], oper: "in", values: ["West"] },
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
      { name: "Old tab", tiles: [] }
    ] },
    style: { style_properties: [{ name: "lb_border_type", value: "SQUARE" }, { name: "hide_group_title", value: "true" }] }
  }
};

let stored = JSON.parse(JSON.stringify(before));
const imports = [];
const ts = {
  async post(url, body) {
    if (url.endsWith("/metadata/tml/export")) return { status: 200, body: [{ edoc: JSON.stringify(stored) }] };
    if (url.endsWith("/searchdata")) return { status: 200, body: { contents: [{ column_names: ["Region", "Total Sales"] }] } };
    if (url.endsWith("/metadata/tml/import")) {
      imports.push(body.import_policy);
      if (body.import_policy === "ALL_OR_NONE") stored = JSON.parse(body.metadata_tmls[0]);
      return { status: 200, body: [{ response: { status: { status_code: "OK" } } }] };
    }
    throw new Error("unexpected call " + url);
  }
};

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
const summary = await new AsyncFunction("ts", block)(ts);
const after = stored.liveboard;
const failures = [];
const expect = (cond, what) => { if (!cond) failures.push(what); };
const viz = (id) => after.visualizations.find((v) => v.id === id);
const tab = (n) => after.layout.tabs.find((t) => t.name === n);

expect(JSON.stringify(imports) === JSON.stringify(["VALIDATE_ONLY", "ALL_OR_NONE"]), "validate then commit, once each");
expect(summary.roundTripAllOk === true, "round trip passes");
expect(JSON.stringify(viz("Viz_1")) === JSON.stringify(native), "native chart kept verbatim");
expect(JSON.stringify(viz("Viz_2")) === JSON.stringify(note), "note kept verbatim");
expect(JSON.stringify(viz("Viz_5")) === JSON.stringify(foreign), "custom chart without the amuzing core kept verbatim");
expect(!viz("Viz_3"), "owned tile no longer in the spec removed");
expect((summary.removed || []).includes("Old chart"), "removed tile reported");
expect(viz("Viz_4") && viz("Viz_4").answer.name === "Guide", "owned tile kept its visualization id");
expect(after.visualizations.length === 5, "five visualizations: three kept, two composed");
expect(JSON.stringify(after.parameters) === JSON.stringify(before.liveboard.parameters), "parameters kept");
const region = after.filters.find((f) => f.column[0] === "region");
expect(region && JSON.stringify(region.values) === '["West"]' && region.display_name === "Region", "spec filter merged, values kept");
const year = after.filters.find((f) => f.column[0] === "year");
expect(year && !("excluded_visualizations" in year), "filter kept, pointer to the removed tile dropped");
expect(after.ordered_chips.some((c) => c.name === "year") && after.ordered_chips.some((c) => c.name === "region"), "chips kept and added");
expect(tab("Notes") && tab("Notes").tiles.length === 2, "tab the spec does not name kept");
expect(tab("Old tab"), "empty tab the user made kept");
const t1 = tab(TAB);
const nat = t1 && t1.tiles.find((t) => t.visualization_id === "Viz_1");
expect(nat && nat.y >= 7, "overlapping native tile moved below the charts");
expect((summary.shiftedBelowCharts || []).includes(TAB), "move reported");
const style = Object.fromEntries(after.style.style_properties.map((p) => [p.name, p.value]));
expect(style.lb_border_type === "CURVED" && style.hide_group_title === "true", "style merged by name");
expect(JSON.stringify(summary.replaced) === '["banner-next"]', "only the sent chart replaced");

console.log(JSON.stringify({ ok: !failures.length, failures, summary }));
