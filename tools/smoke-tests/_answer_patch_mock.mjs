#!/usr/bin/env node
// _answer_patch_mock.mjs — runs the blocks ts-object-answer-chart-builder's helpers/answer-pack.mjs prints against
// an in-memory ThoughtSpot: a mock `ts` answering the REST calls helpers/answer-patch.js makes (model search,
// searchdata, TML export, TML import). Each scenario is a case the answer write path must get right.
//
// Called by smoke_ts_object_answer_chart_builder.py. Prints one PASS/FAIL line per scenario, exits 1 on any FAIL.
// Needs only node; the user's chart library (~/.cache/ts-charts) is kept out by a temporary XDG_CACHE_HOME.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PACK = path.join(ROOT, "agents", "cli", "ts-object-answer-chart-builder", "helpers", "answer-pack.mjs");
const BLOCK = path.join(ROOT, "agents", "cli", "ts-object-answer-chart-builder", "helpers", "mcp-block.mjs");
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "answer-patch-mock-"));
const ENV = { ...process.env, XDG_CACHE_HOME: path.join(TMP, "cache") };
const MODEL = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", ANSWER = "cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee", NEW = "dddddddd-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const SEARCH = "[sales] [region]";
const AsyncFunction = (async () => {}).constructor;
const clone = (x) => JSON.parse(JSON.stringify(x));

function pack(args) {
  const p = spawnSync("node", [PACK, "pulse-kpi-best", "--model", MODEL, "--search", SEARCH, "--name", "Best", ...args], { encoding: "utf8", env: ENV, maxBuffer: 16 << 20 });
  return { code: p.status, block: p.stdout, err: p.stderr };
}
function backup(answer, name = "b.json") {
  const d = path.join(TMP, "backups"); fs.mkdirSync(d, { recursive: true });
  const f = path.join(d, name);
  fs.writeFileSync(f, JSON.stringify([{ edoc: JSON.stringify({ guid: ANSWER, answer }) }]));
  return f;
}
const cols = (q) => [...q.matchAll(/\[([^\]]+)\]/g)].map((m) => (m[1] === "sales" ? "Total Sales" : m[1][0].toUpperCase() + m[1].slice(1)));
function mockTs(state) {
  return { post: async (p, body) => {
    if (p.endsWith("/metadata/search")) return { status: 200, body: [{ metadata_id: MODEL, metadata_name: "M" }] };
    if (p.endsWith("/searchdata")) return { status: 200, body: { contents: [{ column_names: cols(body.query_string) }] } };
    if (p.endsWith("/metadata/tml/export")) {
      const a = state.answers[String(body.metadata[0].identifier).toLowerCase()];
      return a ? { status: 200, body: [{ edoc: JSON.stringify({ guid: body.metadata[0].identifier, answer: a }) }] } : { status: 400, body: {} };
    }
    if (p.endsWith("/metadata/tml/import")) {
      const doc = JSON.parse(body.metadata_tmls[0]);
      const guid = doc.guid || NEW;
      if (body.import_policy === "ALL_OR_NONE") { state.answers[guid] = doc.answer; state.commits = (state.commits || 0) + 1; }
      return { status: 200, body: [{ response: { status: { status_code: "OK" }, header: { id_guid: guid } } }] };
    }
    throw new Error("mock ts: unexpected call " + p);
  } };
}
const run = (block, state) => new AsyncFunction("ts", block)(mockTs(state));

const results = [];
async function scenario(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name + ": " + (e && e.message || e)]); }
}
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

// An answer the user already has: a custom chart with its own state, a table in their column order (not the
// search's, which returns Total Sales first), a formula.
const OLD = {
  name: "Best", search_query: SEARCH, tables: [{ id: "M", name: "M", fqn: MODEL }],
  formulas: [{ id: "f1", name: "Sales per unit", expr: "sum(sales)/sum(quantity)" }],
  answer_columns: [{ name: "Region" }, { name: "Total Sales", format: { category: "CURRENCY" } }],
  table: { table_columns: [{ column_id: "Region" }, { column_id: "Total Sales" }], ordered_column_ids: ["Region", "Total Sales"], client_state: "{\"wrap\":true}", client_state_v2: "{\"tableVizPropVersion\":\"V1\"}" },
  chart: { type: "MUZE_STUDIO", chart_columns: [{ column_id: "Region" }, { column_id: "Total Sales" }], client_state: "{\"user\":\"state\"}", client_state_v2: "{\"version\":\"V4DOT2\",\"columnProperties\":[{\"x\":1}]}", custom_visual_props: JSON.stringify({ clientState: JSON.stringify({ version: 1, playground: { version: "v1", code: { jsCodeBase64: Buffer.from("console.log('user chart');").toString("base64"), cssCodeBase64: "", htmlCodeBase64: Buffer.from("<div id=\"chart\"></div>").toString("base64") } } }) }) },
  display_mode: "CHART_MODE"
};

await scenario("a new answer is created and round-trips", async () => {
  const p = pack(["--commit"]); ok(p.code === 0, "pack: " + p.err);
  const st = { answers: {} };
  const r = await run(p.block, st);
  ok(r.import && r.import.status_code === "OK" && r.roundTripOk === true, JSON.stringify(r).slice(0, 400));
});

await scenario("an update keeps the table's column order and the chart's client_state, and round-trips", async () => {
  const st = { answers: { [ANSWER]: clone(OLD) } };
  const r = await run(pack(["--answer", ANSWER, "--backup", backup(OLD), "--commit"]).block, st);
  ok(r.roundTripOk === true, JSON.stringify(r).slice(0, 400));
  const a = st.answers[ANSWER];
  ok(JSON.stringify(a.table.ordered_column_ids) === JSON.stringify(["Region", "Total Sales"]), "column order reset: " + a.table.ordered_column_ids);
  ok(a.chart.client_state === OLD.chart.client_state, "chart client_state cleared: " + JSON.stringify(a.chart.client_state));
  ok(a.formulas && a.formulas[0].name === "Sales per unit", "formula lost");
});

await scenario("the round trip catches a lost column order or chart state", async () => {
  // A cluster that resets both on import: the commit lands, and the round trip must say so.
  const st = { answers: { [ANSWER]: clone(OLD) } };
  const ts = mockTs(st), post = ts.post;
  ts.post = async (p, body) => {
    const r = await post(p, body);
    if (p.endsWith("/metadata/tml/import") && body.import_policy === "ALL_OR_NONE") { const a = st.answers[ANSWER]; a.table.ordered_column_ids = ["Total Sales", "Region"]; a.chart.client_state = ""; }
    return r;
  };
  const r = await new AsyncFunction("ts", pack(["--answer", ANSWER, "--backup", backup(OLD), "--commit"]).block)(ts);
  ok(r.roundTripOk === false && /column order/.test(r.roundTripFailed.join()) && /client_state/.test(r.roundTripFailed.join()), JSON.stringify(r).slice(0, 400));
});

await scenario("an edit made while the block runs refuses the update", async () => {
  const st = { answers: { [ANSWER]: clone(OLD) } };
  const ts = mockTs(st), post = ts.post;
  let n = 0;
  ts.post = async (p, body) => { if (p.endsWith("/metadata/tml/export") && ++n === 2) st.answers[ANSWER].description = "edited meanwhile"; return post(p, body); };
  const r = await new AsyncFunction("ts", pack(["--answer", ANSWER, "--backup", backup(OLD), "--commit"]).block)(ts);
  ok(r.recheck === "changed" && /changed during the patch/.test(r.refused || "") && !st.commits, JSON.stringify(r).slice(0, 400));
});

await scenario("an update with a backup of an older state, or another answer, is refused", async () => {
  const st = { answers: { [ANSWER]: clone(OLD) } };
  const older = { ...clone(OLD), chart: { ...clone(OLD.chart), type: "COLUMN" } };
  const r = await run(pack(["--answer", ANSWER, "--backup", backup(older, "older.json"), "--commit"]).block, st);
  ok(r.refused && /not of this answer/.test(r.refused) && !st.commits, JSON.stringify(r).slice(0, 400));
  // an older state that differs only in its description
  const olderDesc = { ...clone(OLD), description: "before the edit" };
  const r2 = await run(pack(["--answer", ANSWER, "--backup", backup(olderDesc, "older-desc.json"), "--commit"]).block, st);
  ok(r2.refused && /not of this answer/.test(r2.refused) && !st.commits, JSON.stringify(r2).slice(0, 400));
  ok(pack(["--answer", ANSWER, "--commit"]).code === 2, "an update without --backup was packed");
});

await scenario("a backup exported without fqn (ts tml export's default) is current", async () => {
  const st = { answers: { [ANSWER]: clone(OLD) } };
  const plain = clone(OLD); plain.tables = plain.tables.map(({ fqn, ...t }) => t);
  const r = await run(pack(["--answer", ANSWER, "--backup", backup(plain, "plain.json"), "--commit"]).block, st);
  ok(!r.refused && st.commits, JSON.stringify(r).slice(0, 400));
});

// The read-only intake blocks (helpers/mcp/*.js), printed by mcp-block.mjs.
const block = (...args) => { const p = spawnSync("node", [BLOCK, ...args], { encoding: "utf8", env: ENV }); if (p.status !== 0) throw new Error("mcp-block: " + p.stderr); return p.stdout; };
const readTs = { get: async (p) => (p.endsWith("/auth/session/user") ? { status: 200, body: { name: "u", current_org: { name: "Primary" } } } : { status: 200, body: { name: "cluster" } }),
  post: async (p, body) => {
    if (p.endsWith("/metadata/search")) {
      const m = body.metadata[0];
      if (m.identifier) return { status: 200, body: m.identifier === MODEL ? [{ metadata_id: MODEL, metadata_name: "M", metadata_detail: { columns: [{ header: { name: "Region" }, type: "ATTRIBUTE", dataType: "VARCHAR" }] } }] : [] };
      return { status: 200, body: [{ metadata_id: MODEL, metadata_name: "M", metadata_header: { type: "WORKSHEET" } }, { metadata_id: "t", metadata_name: "T", metadata_header: { type: "ONE_TO_ONE_LOGICAL" } }] };
    }
    if (p.endsWith("/searchdata")) return { status: 200, body: { contents: [{ column_names: /FAIL/.test(body.query_string) ? [] : cols(body.query_string), data_rows: [["West", 10]], record_count: 1 }] } };
    throw new Error("mock ts: unexpected call " + p);
  } };

await scenario("the intake blocks run: models by name, a model's columns, a fixture, a failed search refused", async () => {
  const i = await new AsyncFunction("ts", block("intake", "--words", "retail"))(readTs);
  ok(i.org === "Primary" && i.models.length === 1 && i.models[0].guid === MODEL, JSON.stringify(i));
  const c = await new AsyncFunction("ts", block("model-columns", "--model", MODEL))(readTs);
  ok(c.columns && c.columns[0].name === "Region" && c.columns[0].type === "ATTRIBUTE", JSON.stringify(c));
  const f = JSON.parse(await new AsyncFunction("ts", block("fixture", "--model", MODEL, "--search", SEARCH, "--rows", "1000"))(readTs));
  ok(f.columns.join() === "Total Sales,Region" && f.rows.length === 1, JSON.stringify(f));
  const bad = await new AsyncFunction("ts", block("fixture", "--model", MODEL, "--search", "[FAIL]", "--rows", "10"))(readTs);
  ok(bad.refused, JSON.stringify(bad));
  ok(spawnSync("node", [BLOCK, "fixture", "--model", MODEL]).status === 2, "a block with an unfilled placeholder was printed");
});

fs.rmSync(TMP, { recursive: true, force: true });
for (const [s, m] of results) console.log(s + " " + m);
process.exit(results.some(([s]) => s === "FAIL") ? 1 : 0);
