// Runs ts-object-answer-chart-builder's sandbox code (helpers/answer-patch.js, as packed by answer-pack.mjs)
// against a mock `ts`: once creating a new answer, once updating an answer that has formulas and parameters,
// and checks the update keeps them. Called by smoke_ts_object_answer_chart_builder.py; prints one JSON line:
// { ok, failures, created, updated }.
//
//   node _answer_patch_mock.mjs <chart skill dir> <chart dir>
import path from "node:path";
import { execFileSync } from "node:child_process";

const [skill, chartDir] = process.argv.slice(2);
const GUID = "00000000-0000-0000-0000-0000000000a1";
const pack = (extra) => execFileSync("node", [path.join(skill, "helpers", "answer-pack.mjs"), chartDir, "--model", "Mock model",
  "--search", "[sales] [region]", "--name", "Mock chart", "--commit", ...extra], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });

const existing = {
  guid: GUID,
  answer: {
    name: "Old name", search_query: "[sales] [region] [growth]",
    formulas: [{ id: "f1", name: "growth", expr: "[sales] * 1.1" }],
    parameters: [{ name: "Growth rate", data_type: "DOUBLE" }],
    chart: { type: "COLUMN", chart_columns: [{ column_id: "Region" }], axis_configs: [{ x: ["Region"] }] }
  }
};

function mock() {
  const state = { stored: null, imports: [] };
  state.ts = {
    async post(url, body) {
      if (url.endsWith("/metadata/search")) return { status: 200, body: [{ metadata_id: "m-1", metadata_name: "Mock model" }] };
      if (url.endsWith("/searchdata")) return { status: 200, body: { contents: [{ column_names: ["Region", "Total Sales"] }] } };
      if (url.endsWith("/metadata/tml/export")) {
        const doc = state.stored || existing;
        return { status: 200, body: [{ edoc: JSON.stringify(doc) }] };
      }
      if (url.endsWith("/metadata/tml/import")) {
        state.imports.push(body.import_policy + (body.create_new ? "+new" : ""));
        if (body.import_policy === "ALL_OR_NONE") state.stored = JSON.parse(body.metadata_tmls[0]);
        return { status: 200, body: [{ response: { status: { status_code: "OK" }, header: { id_guid: GUID } } }] };
      }
      throw new Error("unexpected call " + url);
    }
  };
  return state;
}

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
const failures = [];
const expect = (cond, what) => { if (!cond) failures.push(what); };

const a = mock();
const created = await new AsyncFunction("ts", pack([]))(a.ts);
expect(JSON.stringify(a.imports) === '["VALIDATE_ONLY+new","ALL_OR_NONE+new"]', "create: validate then commit, as new");
expect(created.roundTripOk === true, "create: round trip passes");
expect(a.stored && a.stored.answer.chart.type === "MUZE_STUDIO", "create: custom chart");

const b = mock();
const updated = await new AsyncFunction("ts", pack(["--answer", GUID]))(b.ts);
const ans = b.stored && b.stored.answer;
expect(JSON.stringify(b.imports) === '["VALIDATE_ONLY","ALL_OR_NONE"]', "update: validate then commit, in place");
expect(b.stored && b.stored.guid === GUID, "update: same guid");
expect(updated.roundTripOk === true, "update: round trip passes");
expect(ans && JSON.stringify(ans.formulas) === JSON.stringify(existing.answer.formulas), "update: formulas kept");
expect(ans && JSON.stringify(ans.parameters) === JSON.stringify(existing.answer.parameters), "update: parameters kept");
expect(ans && ans.name === "Mock chart" && ans.search_query === "[sales] [region]", "update: name and search replaced");
expect(ans && ans.chart.type === "MUZE_STUDIO" && ans.chart.custom_visual_props && !ans.chart.axis_configs, "update: chart replaced, native axes dropped");
expect((updated.keptFromAnswer || []).includes("formulas"), "update: kept keys reported");

console.log(JSON.stringify({ ok: !failures.length, failures, created, updated }));
