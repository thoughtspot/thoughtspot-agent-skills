// Runs ts-object-answer-chart-builder's sandbox code (helpers/answer-patch.js, as packed by answer-pack.mjs)
// against a mock `ts`: creating a new answer, and updating one that has formulas, parameters, column formats and
// table settings. Checks the update keeps them and says what it kept and replaced, that an update needs a backup,
// and that the round trip notices a formula lost on the server side. Called by
// smoke_ts_object_answer_chart_builder.py; prints one JSON line: { ok, failures, created, updated }.
//
//   node _answer_patch_mock.mjs <chart skill dir> <chart dir>
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const [skill, chartDir] = process.argv.slice(2);
const GUID = "00000000-0000-0000-0000-0000000000a1";
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "answer_mock_"));
const backup = path.join(scratch, "answer-backup.json");
const pack = (extra) => execFileSync("node", [path.join(skill, "helpers", "answer-pack.mjs"), chartDir, "--model", "Mock model",
  "--search", "[sales] [region]", "--name", "Mock chart", "--commit", ...extra], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, XDG_CACHE_HOME: scratch } });
const packFails = (extra) => { try { pack(extra); return false; } catch (e) { return e.status === 2; } };

const existing = {
  guid: GUID,
  answer: {
    name: "Old name", search_query: "[sales] [region] [growth]",
    tables: [{ id: "Mock model", name: "Mock model", fqn: "m-1" }],
    formulas: [{ id: "f1", name: "growth", expr: "[sales] * 1.1" }],
    parameters: [{ name: "Growth rate", data_type: "DOUBLE" }],
    answer_columns: [{ name: "Region" }, { name: "Total Sales", format: { category: "CURRENCY" } }, { name: "growth" }],
    table: { table_columns: [{ column_id: "Total Sales", show_headline: true }], ordered_column_ids: ["Total Sales"], client_state_v2: "{\"wrap\":true}" },
    chart: { type: "COLUMN", chart_columns: [{ column_id: "Region" }], axis_configs: [{ x: ["Region"] }] },
    display_mode: "TABLE_MODE"
  }
};

fs.writeFileSync(backup, JSON.stringify(existing)); // a full export of the answer as it is now

function mock(opts = {}) {
  const state = { stored: null, imports: [] };
  state.ts = {
    async post(url, body) {
      if (url.endsWith("/metadata/search")) return { status: 200, body: [{ metadata_id: "m-1", metadata_name: "Mock model" }] };
      if (url.endsWith("/searchdata")) return { status: 200, body: { contents: [{ column_names: opts.cols || ["Region", "Total Sales"] }] } };
      if (url.endsWith("/metadata/tml/export")) { if (opts.exportDown && state.stored) throw new Error("socket hang up"); return { status: 200, body: [{ edoc: JSON.stringify(state.stored || opts.existing || existing) }] }; }
      if (url.endsWith("/metadata/tml/import")) {
        state.imports.push(body.import_policy + (body.create_new ? "+new" : ""));
        if (body.import_policy === "ALL_OR_NONE") {
          state.stored = JSON.parse(body.metadata_tmls[0]);
          if (opts.loseFormulas) delete state.stored.answer.formulas;
          if (opts.mutate) opts.mutate(state.stored.answer);
        }
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
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const a = mock();
const created = await new AsyncFunction("ts", pack([]))(a.ts);
expect(same(a.imports, ["VALIDATE_ONLY+new", "ALL_OR_NONE+new"]), "create: validate then commit, as new");
expect(created.roundTripOk === true, "create: round trip passes");
expect(a.stored && a.stored.answer.chart.type === "MUZE_STUDIO", "create: custom chart");

// An update needs a backup: the packer refuses without one, or with one of another object.
expect(packFails(["--answer", GUID]), "update: refused without --backup");
const wrong = path.join(scratch, "wrong.json"); fs.writeFileSync(wrong, "{}");
expect(packFails(["--answer", GUID, "--backup", wrong]), "update: refused with a backup of something else");

const b = mock();
const updated = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", backup]))(b.ts);
const ans = b.stored && b.stored.answer;
expect(same(b.imports, ["VALIDATE_ONLY", "ALL_OR_NONE"]), "update: validate then commit, in place");
expect(b.stored && b.stored.guid === GUID, "update: same guid");
expect(updated.roundTripOk === true, "update: round trip passes");
expect(ans && same(ans.formulas, existing.answer.formulas), "update: formulas kept");
expect(ans && same(ans.parameters, existing.answer.parameters), "update: parameters kept");
expect(ans && same(ans.tables, existing.answer.tables), "update: tables kept (they include the model)");
expect(ans && same(ans.answer_columns.find((c) => c.name === "Total Sales"), existing.answer.answer_columns[1]), "update: column format kept");
expect(ans && ans.table.client_state_v2 === "{\"wrap\":true}" && same(ans.table.table_columns.find((c) => c.column_id === "Total Sales"), existing.answer.table.table_columns[0]), "update: table settings kept");
expect(ans && ans.name === "Mock chart" && ans.search_query === "[sales] [region]", "update: name and search replaced");
expect(ans && ans.chart.type === "MUZE_STUDIO" && ans.chart.custom_visual_props && !ans.chart.axis_configs, "update: chart replaced, native axes dropped");
const rep = (updated.replaced || []).join(" | ");
expect(/native COLUMN chart/.test(rep) && /display_mode TABLE_MODE/.test(rep) && /growth/.test(rep), "update: replaced chart, display mode and dropped column reported");
expect((updated.kept || []).includes("formulas") && (updated.kept || []).some((k) => /Total Sales/.test(k)), "update: kept settings reported");

// A formula lost on the server side fails the round trip.
const c = mock({ loseFormulas: true });
const lost = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", backup]))(c.ts);
expect(lost.roundTripOk === false && (lost.roundTripFailed || []).some((x) => /formulas lost: growth/.test(x)), "update: a lost formula fails the round trip");

// A search with no columns is refused, nothing imported.
const e = mock({ cols: [] });
const empty = await new AsyncFunction("ts", pack([]))(e.ts);
expect(/search failed/.test(empty.refused || "") && !e.imports.length, "empty columns: refused, nothing imported");

// A formula whose expression changed on the server fails the round trip.
const fx = mock({ mutate: (a) => { a.formulas[0].expr = "[sales] * 2"; } });
const fxr = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", backup]))(fx.ts);
expect(fxr.roundTripOk === false && (fxr.roundTripFailed || []).some((x) => /formulas changed: growth/.test(x)), "update: a changed formula fails the round trip");

// An export failure after the commit is reported, not thrown.
const ed = mock({ exportDown: true });
const edr = await new AsyncFunction("ts", pack([]))(ed.ts);
expect(edr.roundTripOk === false && /commit landed/.test(edr.roundTripError || ""), "export down after commit: reported, not thrown");

// Updating a custom chart reports its replaced code, field mapping and description; tables of another model
// with the same name are replaced and reported.
const muze = JSON.parse(JSON.stringify(existing));
muze.answer.description = "The user's words";
muze.answer.tables = [{ id: "Mock model", name: "Mock model", fqn: "another-guid" }];
muze.answer.chart = { type: "MUZE_STUDIO", custom_visual_props: "{\"legendVisualProps\":{\"show\":false}}", custom_chart_config: [{ key: "basic", dimensions: [] }] };
const mz = mock({ existing: muze });
const mzr = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", backup, "--description", "New words"]))(mz.ts);
const mrep = (mzr.replaced || []).join(" | ");
expect(/custom_visual_props/.test(mrep) && /custom_chart_config/.test(mrep) && /description/.test(mrep) && /tables/.test(mrep), "update: replaced custom chart settings, description and tables reported");
expect(mz.stored && mz.stored.answer.tables[0].fqn === "m-1", "update: tables of another model replaced");

// The packer: --answer must be a guid; backups must be the answer's own, current, and outside git.
expect(packFails(["--answer", "a", "--backup", backup]), "update: --answer that is not a guid refused");
const future = path.join(scratch, "future.json"); fs.writeFileSync(future, JSON.stringify(existing)); fs.utimesSync(future, new Date("2099-01-01"), new Date("2099-01-01"));
expect(packFails(["--answer", GUID, "--backup", future]), "update: future-dated backup refused");
const mention = path.join(scratch, "mention.json"); fs.writeFileSync(mention, JSON.stringify({ guid: "00000000-0000-0000-0000-0000000000a2", answer: { description: GUID } }));
expect(packFails(["--answer", GUID, "--backup", mention]), "update: backup of another answer that mentions the guid refused");

// Third review: flags without values, all-zero guids, stubs and stale backups.
expect(packFails(["--answer"]), "packer: a trailing --answer with no value exits 2");
const raw = (args) => { try { execFileSync("node", [path.join(skill, "helpers", "answer-pack.mjs"), chartDir, ...args], { stdio: "ignore", env: { ...process.env, XDG_CACHE_HOME: scratch } }); return 0; } catch (e) { return e.status; } };
expect(raw(["--model", "Mock model", "--search", "--name", "n"]) === 2, "packer: `--search --name n` exits 2 instead of searching for \"--name\"");
expect(packFails(["--answer", "00000000-0000-0000-0000-000000000000", "--backup", backup]), "packer: an all-zero guid is refused");
const astub = path.join(scratch, "astub.json"); fs.writeFileSync(astub, JSON.stringify({ guid: GUID, answer: {} }));
expect(packFails(["--answer", GUID, "--backup", astub]), "packer: a stub answer backup is refused");
const astale = path.join(scratch, "astale.json"); fs.writeFileSync(astale, JSON.stringify({ guid: GUID, answer: { ...existing.answer, search_query: "[sales]" } }));
const st = mock();
const str = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", astale]))(st.ts);
expect(/not of this answer as it is now/.test(str.refused || "") && same(st.imports, ["VALIDATE_ONLY"]), "sandbox: a backup of an older answer is refused");

// The round trip allows key order and added defaults, and catches a changed column format.
const ro = mock({ mutate: (a) => { a.formulas = a.formulas.map((f) => ({ expr: f.expr, name: f.name, id: f.id, properties: {} })); } });
const ror = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", backup]))(ro.ts);
expect(ror.roundTripOk === true, "round trip: formula keys reordered and a field added is not a change");
const cf = mock({ mutate: (a) => { a.answer_columns.find((c) => c.name === "Total Sales").format = { category: "NUMBER" }; } });
const cfr = await new AsyncFunction("ts", pack(["--answer", GUID, "--backup", backup]))(cf.ts);
expect(cfr.roundTripOk === false && (cfr.roundTripFailed || []).some((x) => /column settings changed: Total Sales/.test(x)), "round trip: a changed column format fails");

fs.rmSync(scratch, { recursive: true, force: true });
console.log(JSON.stringify({ ok: !failures.length, failures, created, updated }));
